use super::*;

mod errors;

fn fixture() -> (tempfile::TempDir, Arc<Daemon>) {
    use crate::runtime_config::Platform;
    let temp = tempfile::tempdir().unwrap();
    let paths = RuntimePaths::from_env(Platform::Linux, |k| {
        (k == "CODE_DIVER_HOME").then(|| temp.path().display().to_string())
    })
    .unwrap();
    paths.ensure_dirs().unwrap();
    let mut config = RuntimeConfig::default();
    config.daemon.request_timeout_secs = 1;
    config.daemon.startup_timeout_secs = 10;
    config.daemon.idle_timeout_secs = 1;
    config.daemon.max_concurrency = 8;
    config.daemon.log_max_bytes = 24;
    config.daemon.threads = Some(2);
    let binary = temp.path().join("fake-llama");
    std::fs::write(&binary, include_bytes!("../fixtures/fake_daemon_llama.py")).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    config.llama_server = Some(binary);
    let mut manifest = ModelManifest::embedded().unwrap();
    manifest.models.embedder.size = 1;
    manifest.models.reranker.size = 1;
    for spec in [&manifest.models.embedder, &manifest.models.reranker] {
        std::fs::write(paths.models.join(&spec.file), b"x").unwrap();
    }
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(1))
        .build()
        .unwrap();
    (
        temp,
        Arc::new(Daemon {
            config,
            paths,
            manifest,
            client,
            workers: [Mutex::new(Worker::new()), Mutex::new(Worker::new())],
            permits: [Semaphore::new(8), Semaphore::new(8)],
            log: Mutex::new(()),
        }),
    )
}

#[test]
fn limits_flags_hosts_and_semantics() {
    assert!(valid_request(0, &json!({"input":"x".repeat(2000)})));
    assert!(!valid_request(0, &json!({"input":"x".repeat(2001)})));
    assert!(!valid_request(
        1,
        &json!({"query":"q","documents":["x".repeat(48000)]})
    ));
    for host in [
        "evil.test",
        "127.0.0.1.evil",
        "localhost:1",
        "localhost:8090:1",
        "[::1]evil",
    ] {
        assert!(!host_ok(host, 8090));
    }
    assert!(host_ok("[::1]:8090", 8090));
    let mut config = RuntimeConfig::default();
    config.daemon.threads = Some(3);
    let args = child_args(&config, 1, 1234, PathBuf::from("model.gguf"));
    assert!(!args.contains(&"--parallel".into()));
    for value in ["16384", "4096", "3"] {
        assert!(args.contains(&value.into()));
    }
    config.daemon.embedder_ctx = 6000;
    config.daemon.embedder_batch = 3000;
    config.daemon.embedder_ubatch = 1500;
    config.daemon.embedder_pooling = "mean".into();
    let args = child_args(&config, 0, 1234, PathBuf::from("model.gguf"));
    assert!(!args.contains(&"--parallel".into()));
    for value in ["6000", "3000", "1500", "mean"] {
        assert!(args.contains(&value.into()));
    }
    assert_eq!(validate_response(0, 200, br#"{"data":[]}"#).0, 502);
    assert_eq!(validate_response(0, 400, b"secret prompt").0, 400);
    assert!(
        !validate_response(0, 400, b"secret prompt")
            .1
            .to_string()
            .contains("secret")
    );
    let result = validate_response(1,200,br#"{"results":[{"index":0,"relevance_score":0.1},{"index":1,"relevance_score":0.9}],"usage":{"tokens":5}}"#);
    assert_eq!(result.1["results"][0]["index"], 1);
    assert_eq!(result.1["usage"]["tokens"], 5);
}

#[tokio::test]
async fn lifecycle_concurrency_errors_and_rotation() {
    let (_temp, d) = fixture();
    assert_eq!(d.route("GET", "/health", b"").await.0, 200);
    assert!(d.workers[0].lock().await.process.is_none());
    let prompt =
        json!({"input":"<|im_start|>query<|im_end|>","encoding_format":"float","model":"alias"});
    let result = d.proxy(0, prompt.clone()).await;
    assert_eq!(result.0, 200, "{result:?}");
    assert_eq!(result.1["echo"], prompt);
    let port = d.workers[0].lock().await.port;
    let mut jobs = tokio::task::JoinSet::new();
    for _ in 0..8 {
        let d = d.clone();
        jobs.spawn(async move { d.proxy(0, json!({"input":"hello"})).await.0 });
    }
    while let Some(result) = jobs.join_next().await {
        assert_eq!(result.unwrap(), 200);
    }
    assert_eq!(d.workers[0].lock().await.port, port);
    let started = Instant::now();
    for _ in 0..4 {
        let d = d.clone();
        jobs.spawn(async move { d.proxy(0, json!({"input":"slow"})).await.0 });
    }
    while let Some(result) = jobs.join_next().await {
        assert_eq!(result.unwrap(), 200);
    }
    assert!(started.elapsed() < Duration::from_secs(1));
    assert_eq!(
        d.proxy(1, json!({"query":"q","documents":["a","b"]}))
            .await
            .0,
        200
    );
    assert_ne!(d.workers[1].lock().await.port, port);
    assert_eq!(d.proxy(0, json!({"input":"long"})).await.0, 400);
    assert_eq!(d.proxy(0, json!({"input":["incomplete","b"]})).await.0, 502);
    assert_eq!(
        d.route(
            "POST",
            "/v1/rerank",
            &serde_json::to_vec(&json!({"query":"token ".repeat(3300),"documents":["a"]})).unwrap()
        )
        .await
        .0,
        400
    );
    assert_eq!(d.proxy(0, json!({"input":"timeout"})).await.0, 504);
    tokio::time::sleep(Duration::from_millis(1100)).await;
    d.reap_idle().await;
    assert!(d.workers[0].lock().await.process.is_none());
    assert!(d.workers[1].lock().await.process.is_none());
    assert_eq!(d.proxy(0, json!({"input":"hello"})).await.0, 200);
    for _ in 0..8 {
        d.event(0, "child_started").await.unwrap();
    }
    for name in ["embedder.log", "embedder.log.1", "embedder.log.2"] {
        assert!(std::fs::metadata(d.paths.logs.join(name)).unwrap().len() <= 24);
        assert!(
            !std::fs::read_to_string(d.paths.logs.join(name))
                .unwrap()
                .contains("synthetic-secret")
        );
    }
    assert!(!d.paths.logs.join("embedder.log.3").exists());
    for worker in &d.workers {
        worker.lock().await.stop().await;
    }
}

#[tokio::test]
async fn exported_run_http_and_idle_shutdown() {
    let (_temp, d) = fixture();
    std::fs::write(
        d.paths
            .models
            .join(format!("{}.startup-delay", d.manifest.models.embedder.file)),
        b"1.2",
    )
    .unwrap();
    let reserve = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = reserve.local_addr().unwrap().port();
    drop(reserve);
    let mut config = d.config.clone();
    config.daemon.port = port;
    config.daemon.startup_timeout_secs = 10;
    let manifest = d.paths.state.join("manifest.json");
    std::fs::write(&manifest, serde_json::to_vec(&d.manifest).unwrap()).unwrap();
    config.profile.model_manifest_path = Some(manifest);
    let task = tokio::spawn(run(config, d.paths.clone(), true));
    let base = format!("http://127.0.0.1:{port}");
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(15))
        .build()
        .unwrap();
    let mut ready = false;
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        if client
            .get(format!("{base}/health"))
            .send()
            .await
            .is_ok_and(|r| r.status().is_success())
        {
            ready = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(ready);
    assert!(!d.paths.logs.join("embedder.log").exists());
    let result = client
        .post(format!("{base}/v1/embeddings"))
        .json(&json!({"input":"hello"}))
        .send()
        .await
        .unwrap();
    assert_eq!(result.status(), 200);
    for (endpoint, request, valid) in [
        (
            "/v1/embeddings",
            json!({"input":"overflow"}),
            json!({"input":"hello"}),
        ),
        (
            "/v1/rerank",
            json!({"query":"overflow","documents":["hello","world"]}),
            json!({"query":"hello","documents":["hello","world"]}),
        ),
    ] {
        let rejected = client
            .post(format!("{base}{endpoint}"))
            .json(&request)
            .send()
            .await
            .unwrap();
        assert_eq!(rejected.status(), 400);
        let body = rejected.text().await.unwrap();
        assert!(body.contains("context length exceeded"));
        assert!(!body.contains("synthetic-secret"));
        assert!(!body.contains("20074"));
        assert_eq!(
            client
                .get(format!("{base}/health"))
                .send()
                .await
                .unwrap()
                .status(),
            200
        );
        assert_eq!(
            client
                .post(format!("{base}{endpoint}"))
                .json(&valid)
                .send()
                .await
                .unwrap()
                .status(),
            200
        );
    }
    let args: Vec<String> = serde_json::from_slice(
        &std::fs::read(
            d.paths
                .models
                .join(format!("{}.args.json", d.manifest.models.embedder.file)),
        )
        .unwrap(),
    )
    .unwrap();
    for value in ["5120", "2560", "--threads", "2", "last"] {
        assert!(args.contains(&value.to_string()));
    }
    let environment: std::collections::BTreeMap<String, String> = serde_json::from_slice(
        &std::fs::read(
            d.paths
                .models
                .join(format!("{}.env.json", d.manifest.models.embedder.file)),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(environment.get("PATH"), std::env::var("PATH").ok().as_ref());
    // Python coerces the locale; macOS adds its CoreFoundation encoding marker.
    assert!(
        environment.keys().all(|key| {
            key == "PATH"
                || key == "LC_CTYPE"
                || (cfg!(target_os = "macos") && key == "__CF_USER_TEXT_ENCODING")
        }),
        "unexpected environment keys: {:?}",
        environment.keys().collect::<Vec<_>>()
    );
    assert_eq!(
        client
            .post(format!("{base}/v1/embeddings"))
            .json(&json!({"input":"x".repeat(2001)}))
            .send()
            .await
            .unwrap()
            .status(),
        400
    );
    assert_eq!(
        client
            .get(format!("{base}/health"))
            .header("Host", "evil.test")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let health: Value = client
            .get(format!("{base}/health"))
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        if health["children"][0]["loaded"] == false {
            break;
        }
        assert!(Instant::now() < deadline, "child did not unload: {health}");
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
}

#[tokio::test]
async fn crash_restart_is_capped() {
    let (_temp, d) = fixture();
    assert_eq!(d.proxy(0, json!({"input":"crash_once"})).await.0, 200);
    assert_eq!(d.workers[0].lock().await.failures, 1);
    for _ in 0..4 {
        assert_eq!(d.proxy(0, json!({"input":"crash"})).await.0, 503);
    }
    assert_eq!(
        d.proxy(0, json!({"input":"hello"})).await.1["error"]["type"],
        "restart_limit"
    );
    d.workers[0].lock().await.stop().await;
}

#[tokio::test]
async fn http_security() {
    for (headers, status) in [
        ("Host: evil.test\r\n", 403),
        (
            "Host: localhost\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n",
            415,
        ),
        ("Host: localhost\r\nHost: localhost\r\n", 400),
        ("Host: localhost\r\nOrigin: http://evil.test\r\n", 403),
        ("Host: localhost\r\nTransfer-Encoding: chunked\r\n", 403),
    ] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let task = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream, address.port())
                .await
                .unwrap_err()
                .0
        });
        let mut stream = TcpStream::connect(address).await.unwrap();
        stream
            .write_all(format!("POST /v1/embeddings HTTP/1.1\r\n{headers}\r\n").as_bytes())
            .await
            .unwrap();
        assert_eq!(task.await.unwrap(), status);
    }
}
