use serde_json::{Value, json};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::time::Duration;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let name = PathBuf::from(&args[0]);
    if name
        .file_stem()
        .unwrap()
        .to_string_lossy()
        .starts_with("runtime_test_helper-")
    {
        return;
    }
    if name.file_name().unwrap() == "claude" {
        host(&args[1..]);
        return;
    }
    let acceptance = name.file_name().unwrap() == "llama-server";
    if acceptance {
        let log = name
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("runtime/llama-args");
        writeln!(
            OpenOptions::new()
                .create(true)
                .append(true)
                .open(log)
                .unwrap(),
            "{}",
            json!(args)
        )
        .unwrap();
    }
    if args.iter().any(|arg| arg == "--version") {
        println!("version: 9430");
        return;
    }
    let flag = |key: &str| args[args.iter().position(|arg| arg == key).unwrap() + 1].clone();
    let port: u16 = flag("--port").parse().unwrap();
    let model = flag("--model");
    if !acceptance {
        fs::write(format!("{model}.args.json"), json!(&args[1..]).to_string()).unwrap();
        fs::write(
            format!("{model}.env.json"),
            json!(std::env::vars().collect::<std::collections::BTreeMap<_, _>>()).to_string(),
        )
        .unwrap();
        if let Ok(delay) = fs::read_to_string(format!("{model}.startup-delay")) {
            std::thread::sleep(Duration::from_secs_f64(delay.trim().parse().unwrap()));
        }
        println!("synthetic-secret raw child output");
        eprintln!("synthetic-secret raw child output");
    }
    for stream in TcpListener::bind(("127.0.0.1", port)).unwrap().incoming() {
        let model = model.clone();
        std::thread::spawn(move || serve(stream.unwrap(), &model, acceptance));
    }
}

fn host(args: &[String]) {
    let path = PathBuf::from(std::env::var_os("CLAUDE_CONFIG_DIR").unwrap()).join(".claude.json");
    let mut value: Value = fs::read(&path)
        .map(|bytes| serde_json::from_slice(&bytes).unwrap())
        .unwrap_or_else(|_| json!({"mcpServers":{}}));
    match args.get(1).map(String::as_str) {
        Some("add") if args[0] == "mcp" => {
            let mut env = serde_json::Map::new();
            for pair in args.windows(2) {
                if pair[0] == "--env" {
                    let (key, value) = pair[1].split_once('=').unwrap();
                    env.insert(key.into(), json!(value));
                }
            }
            let tail = &args[args.iter().position(|arg| arg == "--").unwrap() + 1..];
            value["mcpServers"]["code-diver"] =
                json!({"type":"stdio","command":tail[0],"args":&tail[1..],"env":env});
        }
        Some("remove") if args[0] == "mcp" => {
            value["mcpServers"]
                .as_object_mut()
                .unwrap()
                .remove("code-diver");
        }
        _ => std::process::exit(1),
    }
    fs::write(path, value.to_string()).unwrap();
}

fn serve(mut stream: TcpStream, model: &str, acceptance: bool) {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    let mut head = Vec::new();
    while !head.ends_with(b"\r\n\r\n") {
        let mut byte = [0];
        if stream.read_exact(&mut byte).is_err() {
            return;
        }
        head.push(byte[0]);
    }
    let head = String::from_utf8(head).unwrap();
    let (status, response) = if head.starts_with("GET ") {
        (200, json!({"status":"ok"}))
    } else {
        let length: usize = head
            .lines()
            .find_map(|line| {
                let (key, value) = line.split_once(':')?;
                key.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse().unwrap())
            })
            .unwrap();
        let mut body = vec![0; length];
        stream.read_exact(&mut body).unwrap();
        let value: Value = serde_json::from_slice(&body).unwrap();
        let text = value
            .get("query")
            .or_else(|| value.get("input"))
            .and_then(Value::as_str)
            .unwrap_or("");
        if !acceptance {
            if text == "crash"
                || (text == "crash_once" && !PathBuf::from(format!("{model}.crashed")).exists())
            {
                fs::write(format!("{model}.crashed"), "").unwrap();
                std::process::exit(1);
            }
            match text {
                "slow" => std::thread::sleep(Duration::from_millis(300)),
                "timeout" => std::thread::sleep(Duration::from_secs(2)),
                _ => (),
            }
        }
        if !acceptance && text == "overflow" {
            (
                500,
                json!({"error":{"message":"input (20074 tokens) is too large to process. increase the physical batch size (current batch size: 4096) synthetic-secret"}}),
            )
        } else if !acceptance && (text == "long" || text.split_whitespace().count() >= 3300) {
            (
                500,
                json!({"error":{"message":"input too large to process: synthetic-secret"}}),
            )
        } else if head.split_whitespace().nth(1).unwrap().ends_with("rerank") {
            let results = if acceptance {
                value["documents"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .enumerate()
                    .map(|(index, _)| json!({"index":index,"relevance_score":0.9}))
                    .collect::<Vec<_>>()
            } else {
                vec![
                    json!({"index":0,"relevance_score":0.1}),
                    json!({"index":1,"relevance_score":0.9}),
                ]
            };
            (200, json!({"results":results}))
        } else {
            let count = value["input"].as_array().map_or(1, |inputs| {
                if !acceptance && inputs.first().is_some_and(|input| input == "incomplete") {
                    1
                } else {
                    inputs.len()
                }
            });
            let data: Vec<_> = (0..count)
                .map(|index| json!({"index":index,"embedding":[0.6,0.8]}))
                .collect();
            (200, json!({"data":data,"echo":value}))
        }
    };
    let body = response.to_string();
    let _ = write!(
        stream,
        "HTTP/1.1 {status} Response\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
}
