use std::fmt;
use std::str::FromStr;
use std::time::Duration;

use reqwest::header::{AUTHORIZATION, HeaderMap, HeaderValue};
use serde_json::Value;

#[derive(Clone, Default)]
pub struct Secret(pub String);

impl fmt::Debug for Secret {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("[redacted]")
    }
}

impl FromStr for Secret {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, String> {
        Ok(Self(s.to_string()))
    }
}

pub fn client(
    api_key: &Secret,
    bearer: &Secret,
    ca: Option<&str>,
    insecure: bool,
    timeout_ms: u64,
) -> Result<reqwest::Client, String> {
    let mut headers = HeaderMap::new();
    for (name, raw) in [
        ("api-key", api_key.0.clone()),
        (
            AUTHORIZATION.as_str(),
            if bearer.0.is_empty() {
                String::new()
            } else {
                format!("Bearer {}", bearer.0)
            },
        ),
    ] {
        if !raw.is_empty() {
            let mut value = HeaderValue::from_str(&raw).map_err(|_| "Invalid credential header")?;
            value.set_sensitive(true);
            headers.insert(
                reqwest::header::HeaderName::from_bytes(name.as_bytes()).unwrap(),
                value,
            );
        }
    }
    let mut builder = reqwest::Client::builder()
        .default_headers(headers)
        .timeout(Duration::from_millis(timeout_ms))
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            if attempt.previous().len() >= 5 {
                return attempt.error("Too many redirects");
            }
            let same = attempt.previous().last().is_none_or(|previous| {
                previous.scheme() == attempt.url().scheme()
                    && previous.host_str() == attempt.url().host_str()
                    && previous.port_or_known_default() == attempt.url().port_or_known_default()
            });
            if same {
                attempt.follow()
            } else {
                attempt.stop()
            }
        }));
    if let Some(path) = ca {
        let bytes = std::fs::read(path).map_err(|_| "Cannot read CA bundle; check --ca-bundle")?;
        let certs =
            reqwest::Certificate::from_pem_bundle(&bytes).map_err(|_| "Invalid CA bundle")?;
        if certs.is_empty() {
            return Err("CA bundle contains no certificates".into());
        }
        for cert in certs {
            builder = builder.add_root_certificate(cert);
        }
    }
    if insecure {
        eprintln!(
            "WARNING: --insecure-skip-verify disables TLS certificate verification; credentials can be intercepted"
        );
        builder = builder.danger_accept_invalid_certs(true);
    }
    builder
        .build()
        .map_err(|_| "Cannot build HTTP client".into())
}

pub async fn request(
    client: &reqwest::Client,
    method: reqwest::Method,
    url: &str,
    body: Option<&Value>,
) -> Result<reqwest::Response, String> {
    request_with_timeout(client, method, url, body, None).await
}

pub async fn request_with_timeout(
    client: &reqwest::Client,
    method: reqwest::Method,
    url: &str,
    body: Option<&Value>,
    timeout: Option<Duration>,
) -> Result<reqwest::Response, String> {
    for attempt in 0..3 {
        let mut request = client.request(method.clone(), url);
        if let Some(timeout) = timeout {
            request = request.timeout(timeout);
        }
        if let Some(body) = body {
            request = request.json(body);
        }
        match request.send().await {
            Ok(response) => {
                if !(response.status().is_server_error() || response.status().as_u16() == 429)
                    || attempt == 2
                {
                    return Ok(response);
                }
            }
            Err(error) if attempt == 2 => {
                return Err(if error.is_timeout() {
                    "Index request timed out; check service or increase --timeout-ms".into()
                } else {
                    "Index request failed; check service URL, TLS trust and connectivity".into()
                });
            }
            Err(_) => {}
        }
        tokio::time::sleep(Duration::from_millis(100 * (1 << attempt))).await;
    }
    unreachable!()
}

pub async fn json(response: reqwest::Response) -> Result<Value, String> {
    if !response.status().is_success() {
        return Err(format!(
            "Index service HTTP {}; check credentials, collection and request settings",
            response.status().as_u16()
        ));
    }
    response
        .json()
        .await
        .map_err(|_| "Invalid index service JSON response".into())
}

fn context_overflow(status: u16, body: &str) -> bool {
    let body = body.to_ascii_lowercase();
    status == 400
        && [
            "context length",
            "context_length",
            "maximum context",
            "too many tokens",
            "max input tokens",
        ]
        .iter()
        .any(|marker| body.contains(marker))
}

// Keep error bodies private: inspect only to classify an actionable context overflow.
async fn embedding_attempt(
    client: &reqwest::Client,
    url: &str,
    body: &Value,
) -> Result<Option<Value>, String> {
    let response = request(client, reqwest::Method::POST, url, Some(body)).await?;
    let status = response.status().as_u16();
    if status == 400 {
        let text = response
            .text()
            .await
            .map_err(|_| "Cannot read embedding response")?;
        if context_overflow(status, &text) {
            return Ok(None);
        }
        return Err("Embedding HTTP 400; check request settings".into());
    }
    json(response).await.map(Some)
}

pub async fn embedding_request(
    client: &reqwest::Client,
    url: &str,
    body: &Value,
) -> Result<Value, String> {
    if let Some(data) = embedding_attempt(client, url, body).await? {
        return Ok(data);
    }
    let texts: Vec<String> = match &body["input"] {
        Value::String(text) => vec![text.clone()],
        Value::Array(texts) => texts
            .iter()
            .map(|text| {
                text.as_str()
                    .map(str::to_string)
                    .ok_or("Invalid embedding input".to_string())
            })
            .collect::<Result<_, _>>()?,
        _ => return Err("Invalid embedding input".into()),
    };
    let mut rows = Vec::new();
    for (index, text) in texts.iter().enumerate() {
        let mut current = text.clone();
        let mut item_body = body.clone();
        let mut data = None;
        if texts.len() > 1 {
            item_body["input"] = serde_json::json!([current]);
            data = embedding_attempt(client, url, &item_body).await?;
        }
        for _ in 0..2 {
            if data.is_some() {
                break;
            }
            current = current
                .chars()
                .take((current.chars().count() / 2).max(1))
                .collect();
            item_body["input"] = serde_json::json!([current]);
            eprintln!(
                "Embedding context overflow: retrying one item with reduced character budget (estimated tokens)"
            );
            data = embedding_attempt(client, url, &item_body).await?;
        }
        let data = data.ok_or("Embedding context overflow after two shrinking retries")?;
        let mut row = data["data"]
            .as_array()
            .filter(|rows| rows.len() == 1)
            .and_then(|rows| rows.first())
            .cloned()
            .ok_or("Embedding retry response count mismatch")?;
        row["index"] = serde_json::json!(index);
        rows.push(row);
    }
    Ok(serde_json::json!({"data": rows}))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn credentials_are_redacted_and_invalid_headers_are_sanitized() {
        assert!(!format!("{:?}", Secret("top-secret".into())).contains("top-secret"));
        let error = client(
            &Secret("bad\nsecret-xyz".into()),
            &Secret::default(),
            None,
            false,
            100,
        )
        .unwrap_err();
        assert!(!error.contains("secret-xyz"));
    }

    #[test]
    fn rejects_invalid_ca_bundles() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("invalid.pem");
        std::fs::write(&path, "not a certificate").unwrap();
        assert!(
            client(
                &Secret::default(),
                &Secret::default(),
                Some(path.to_str().unwrap()),
                false,
                100
            )
            .is_err()
        );
    }

    #[tokio::test]
    async fn cross_origin_redirect_does_not_forward_credentials() {
        use std::io::{Read, Write};
        let target = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        target.set_nonblocking(true).unwrap();
        let source = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let source_url = format!("http://{}/start", source.local_addr().unwrap());
        let target_url = format!("http://{}/stolen", target.local_addr().unwrap());
        let server = std::thread::spawn(move || {
            let (mut stream, _) = source.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            let mut buffer = [0; 4096];
            let count = stream.read(&mut buffer).unwrap();
            assert!(
                String::from_utf8_lossy(&buffer[..count]).contains("api-key: synthetic-secret")
            );
            write!(stream, "HTTP/1.1 302 Found\r\nlocation: {target_url}\r\ncontent-length: 0\r\nconnection: close\r\n\r\n").unwrap();
        });
        let client = client(
            &Secret("synthetic-secret".into()),
            &Secret::default(),
            None,
            false,
            2000,
        )
        .unwrap();
        assert_eq!(
            request(&client, reqwest::Method::GET, &source_url, None)
                .await
                .unwrap()
                .status()
                .as_u16(),
            302
        );
        server.join().unwrap();
        assert_eq!(
            target.accept().unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
    }
}
