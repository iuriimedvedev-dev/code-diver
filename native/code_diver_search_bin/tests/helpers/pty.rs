use std::fs::File;
use std::io::{Read, Write};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::process::CommandExt;
use std::process::{Command, Output, Stdio};
use std::time::{Duration, Instant};

pub fn pty_setup(mut command: Command, profile: &str, key: &str) -> Output {
    let (mut master, mut slave) = (-1, -1);
    assert_eq!(
        unsafe {
            libc::openpty(
                &mut master,
                &mut slave,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        },
        0
    );
    let mut terminal = unsafe { File::from_raw_fd(master) };
    let slave = unsafe { File::from_raw_fd(slave) };
    command
        .stdin(Stdio::null())
        .stdout(slave.try_clone().unwrap())
        .stderr(slave);
    unsafe {
        command.pre_exec(|| {
            if libc::setsid() < 0 || libc::ioctl(1, libc::TIOCSCTTY as _, 0) < 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let mut child = super::Process(command.spawn().unwrap());
    drop(command);
    let mut transcript = Vec::new();
    let pending = [
        ("Team profile URL or file: ", profile),
        ("Read-only Qdrant key: ", key),
    ];
    let mut sent = 0;
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        assert!(Instant::now() < deadline, "PTY setup did not finish");
        let mut poll = libc::pollfd {
            fd: terminal.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        let ready = unsafe { libc::poll(&mut poll, 1, 100) };
        assert!(ready >= 0, "PTY poll failed");
        if ready == 0 {
            continue;
        }
        let mut bytes = [0; 65536];
        match terminal.read(&mut bytes) {
            Ok(0) => break,
            Ok(count) => transcript.extend_from_slice(&bytes[..count]),
            Err(error) if error.raw_os_error() == Some(libc::EIO) => break,
            Err(error) => panic!("PTY read: {error}"),
        }
        if sent < pending.len() && String::from_utf8_lossy(&transcript).contains(pending[sent].0) {
            writeln!(terminal, "{}", pending[sent].1).unwrap();
            sent += 1;
        }
    }
    assert_eq!(
        sent,
        pending.len(),
        "setup did not prompt for profile and key"
    );
    let status = loop {
        if let Some(status) = child.0.try_wait().unwrap() {
            break status;
        }
        assert!(Instant::now() < deadline, "PTY child did not exit");
        std::thread::sleep(Duration::from_millis(10));
    };
    Output {
        status,
        stdout: transcript,
        stderr: Vec::new(),
    }
}
