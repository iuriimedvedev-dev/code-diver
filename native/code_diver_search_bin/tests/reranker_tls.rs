use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};

struct Server(Child);

impl Drop for Server {
    fn drop(&mut self) {
        self.0.kill().unwrap();
        self.0.wait().unwrap();
    }
}

#[test]
fn search_reranker_shares_tls_policy_without_service_credentials() {
    let dir = tempfile::tempdir().unwrap();
    let openssl = |args: &[&str]| {
        let output = Command::new("openssl")
            .current_dir(dir.path())
            .args(args)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
    };
    openssl(&[
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.pem",
        "-days",
        "1",
        "-subj",
        "/CN=M3 Test CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
    ]);
    openssl(&[
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "leaf.key",
        "-out",
        "leaf.csr",
        "-subj",
        "/CN=localhost",
    ]);
    std::fs::write(dir.path().join("leaf.ext"), "basicConstraints=critical,CA:FALSE\nsubjectAltName=IP:127.0.0.1\nextendedKeyUsage=serverAuth\n").unwrap();
    openssl(&[
        "x509",
        "-req",
        "-in",
        "leaf.csr",
        "-CA",
        "ca.pem",
        "-CAkey",
        "ca.key",
        "-CAcreateserial",
        "-out",
        "leaf.pem",
        "-days",
        "1",
        "-extfile",
        "leaf.ext",
    ]);
    let script = r#"
const https = require('node:https'), fs = require('node:fs');
const server = https.createServer({key:fs.readFileSync('leaf.key'),cert:fs.readFileSync('leaf.pem')}, async (req,res) => {
 let raw=''; for await (const chunk of req) raw+=chunk;
 const body=JSON.parse(raw);
 const rerank=req.url.includes('rerank');
 if (rerank && (req.headers.authorization || req.headers['api-key'])) {res.writeHead(403);res.end('{}');return;}
 if (!rerank && (req.url.includes('embeddings') ? req.headers.authorization !== 'Bearer e-secret' || req.headers['api-key'] : req.headers['api-key'] !== 'q-secret' || req.headers.authorization)) {res.writeHead(403);res.end('{}');return;}
 if (rerank) fs.appendFileSync('rerank-calls', 'rerank\n');
 res.setHeader('Content-Type','application/json');
 res.end(JSON.stringify(rerank ? {results:body.documents.map((_,index)=>({index,relevance_score:0.8}))} : req.url.includes('embeddings') ? {data:[{embedding:[1,2,3,4]}]} : {result:[]}));
});
server.listen(0,'127.0.0.1',()=>console.log('https://127.0.0.1:'+server.address().port));
"#;
    let mut server = Server(
        Command::new("node")
            .args(["-e", script])
            .current_dir(dir.path())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    let mut url = String::new();
    BufReader::new(server.0.stdout.take().unwrap())
        .read_line(&mut url)
        .unwrap();
    let url = url.trim();
    assert!(url.starts_with("https://127.0.0.1:"));
    std::fs::write(
        dir.path().join("a.md"),
        "# Alpha\nAuthentication token validation",
    )
    .unwrap();
    assert!(
        Command::new(env!("CARGO_BIN_EXE_code-diver"))
            .env("TOKIO_WORKER_THREADS", "2")
            .args(["index", "--catalog-only", "--root"])
            .arg(dir.path())
            .output()
            .unwrap()
            .status
            .success()
    );
    std::fs::write(dir.path().join(".code-diver/rust_graph.jsonl"), "").unwrap();
    let config = dir.path().join("search.toml");
    std::fs::write(&config, format!("catalog = '.code-diver/rust_catalog.jsonl'\ngraph_path = '.code-diver/rust_graph.jsonl'\n[storage.qdrant]\nurl = '{url}'\ncollection = 'zz_tls'\napi_key = 'q-secret'\n[embedding]\nurl = '{url}/embeddings'\napi_key = 'e-secret'\n")).unwrap();
    for mode in ["strict", "ca", "insecure"] {
        let mut command = Command::new(env!("CARGO_BIN_EXE_code-diver"));
        command
            .env("TOKIO_WORKER_THREADS", "2")
            .args(["search", "--query", "Alpha", "--config"])
            .arg(&config)
            .args(["--ce-url", &format!("{url}/rerank")]);
        if mode == "ca" {
            command.arg("--ca-bundle").arg(dir.path().join("ca.pem"));
        }
        if mode == "insecure" {
            command.arg("--insecure-skip-verify");
        }
        let output = command.output().unwrap();
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert_eq!(
            output.status.success(),
            mode != "strict",
            "{mode}: {stderr}"
        );
        assert!(!stderr.contains("q-secret") && !stderr.contains("e-secret"));
        if mode != "strict" {
            assert!(
                String::from_utf8_lossy(&output.stdout).contains("Alpha"),
                "{stderr}"
            );
        }
        if mode == "insecure" {
            assert!(stderr.contains("WARNING"));
        }
    }
    assert_eq!(
        std::fs::read_to_string(dir.path().join("rerank-calls")).unwrap(),
        "rerank\nrerank\n"
    );
}
