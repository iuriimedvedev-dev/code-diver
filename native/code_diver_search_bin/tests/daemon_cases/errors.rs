use super::*;

#[tokio::test]
async fn backend_overflow_is_sanitized_and_children_survive() {
    let (_temp, d) = fixture();
    for role in [0, 1] {
        let request = if role == 0 {
            json!({"input":"overflow"})
        } else {
            json!({"query":"overflow","documents":["hello","world"]})
        };
        let rejected = d.proxy(role, request).await;
        assert_eq!(rejected.0, 400, "{rejected:?}");
        assert!(rejected.1.to_string().contains("context length exceeded"));
        assert!(!rejected.1.to_string().contains("synthetic-secret"));
        let pid = d.workers[role].lock().await.process.as_ref().unwrap().id();
        assert_eq!(d.route("GET", "/health", b"").await.0, 200);
        let valid = if role == 0 {
            json!({"input":["hello","world"]})
        } else {
            json!({"query":"hello","documents":["hello","world"]})
        };
        assert_eq!(d.proxy(role, valid).await.0, 200);
        assert_eq!(
            d.workers[role].lock().await.process.as_ref().unwrap().id(),
            pid
        );
        d.workers[role].lock().await.stop().await;
    }
    let rejected = d
        .route(
            "POST",
            "/v1/embeddings",
            &serde_json::to_vec(&json!({"input":"x ".repeat(3300)})).unwrap(),
        )
        .await;
    assert_eq!(rejected.0, 400);
    assert_eq!(d.route("GET", "/health", b"").await.0, 200);
}

#[tokio::test]
async fn oversized_existing_log_is_capped() {
    let (_temp, d) = fixture();
    std::fs::write(d.paths.logs.join("embedder.log"), vec![b'x'; 100]).unwrap();
    d.event(0, "child_started").await.unwrap();
    for name in ["embedder.log", "embedder.log.1"] {
        assert!(std::fs::metadata(d.paths.logs.join(name)).unwrap().len() <= 24);
    }
}

#[tokio::test]
async fn loopback_malformed_and_error_responses() {
    for (status, body, expected) in [
        (200, "not json", 502),
        (200, r#"{"data":[]}"#, 502),
        (200, r#"{"data":[{"embedding":[0,0]}]}"#, 502),
        (400, r#"{"error":"synthetic-secret"}"#, 400),
        (500, r#"{"error":"synthetic-secret"}"#, 503),
        (
            500,
            r#"{"error":{"message":"input processing failed with batch size 4096: synthetic-secret"}}"#,
            503,
        ),
        (
            500,
            r#"{"error":{"message":"input (20074 tokens) is too large to process. increase the physical batch size (current batch size: 4096) synthetic-secret"}}"#,
            400,
        ),
        (
            500,
            r#"{"error":{"message":"input too large to process: synthetic-secret"}}"#,
            400,
        ),
        (
            400,
            r#"{"error":"context_length_exceeded synthetic-secret"}"#,
            400,
        ),
        (
            500,
            r#"{"error":"synthetic-secret","input":"input too large to process"}"#,
            503,
        ),
        (
            504,
            r#"{"error":"input too large to process synthetic-secret"}"#,
            504,
        ),
        (504, "timeout", 504),
    ] {
        let (_temp, d) = fixture();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let mock = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let (_, _, body_received) = read_request(&mut stream, port).await.unwrap();
            assert_eq!(
                serde_json::from_slice::<Value>(&body_received).unwrap()["input"],
                "hello"
            );
            stream.write_all(format!("HTTP/1.1 {status} Response\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        });
        let mut child = Command::new("/bin/sleep");
        child.arg("30").kill_on_drop(true);
        {
            let mut worker = d.workers[0].lock().await;
            worker.port = port;
            worker.process = Some(child.spawn().unwrap());
        }
        let reply = d.proxy(0, json!({"input":"hello"})).await;
        assert_eq!(reply.0, expected);
        assert!(!reply.1.to_string().contains("synthetic-secret"));
        mock.await.unwrap();
        d.workers[0].lock().await.stop().await;
    }
}

#[tokio::test]
async fn missing_model_and_startup_timeout() {
    let (_temp, mut d) = fixture();
    Arc::get_mut(&mut d)
        .unwrap()
        .config
        .daemon
        .startup_timeout_secs = 1;
    std::fs::remove_file(d.paths.models.join(&d.manifest.models.embedder.file)).unwrap();
    assert_eq!(
        d.proxy(0, json!({"input":"hello"})).await.1["error"]["type"],
        "model_missing_or_invalid"
    );
    std::fs::write(d.paths.models.join(&d.manifest.models.embedder.file), b"x").unwrap();
    let binary = d.config.llama_server.as_ref().unwrap();
    std::fs::write(binary, b"#!/bin/sh\nexec /bin/sleep 30\n").unwrap();
    assert_eq!(d.proxy(0, json!({"input":"hello"})).await.0, 504);
    assert!(d.workers[0].lock().await.process.is_none());
}
