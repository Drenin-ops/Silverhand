from unittest.mock import patch, MagicMock


def test_returns_bytes_on_success():
    fake_pcm = b"\x01\x00" * 800

    with patch("audio.tts.prep", return_value="hello"), \
         patch("audio.tts.cfg") as mock_cfg, \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("subprocess.run") as mock_run, \
         patch("os.path.getsize", return_value=100), \
         patch("os.path.exists", return_value=True), \
         patch("os.remove"):
        mock_cfg.piper_exe = "piper"
        mock_cfg.piper_model = "model.onnx"
        mock_ntf.return_value.__enter__.return_value.name = "/tmp/fake.wav"
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout=fake_pcm),
        ]
        from audio.tts import piper_to_pcm
        assert piper_to_pcm("hello") == fake_pcm


def test_returns_none_when_piper_fails():
    with patch("audio.tts.prep", return_value="hello"), \
         patch("audio.tts.cfg"), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("subprocess.run") as mock_run, \
         patch("os.path.getsize", return_value=0), \
         patch("os.path.exists", return_value=True), \
         patch("os.remove"):
        mock_ntf.return_value.__enter__.return_value.name = "/tmp/fake.wav"
        mock_run.return_value = MagicMock(returncode=1)
        from audio.tts import piper_to_pcm
        assert piper_to_pcm("hello") is None


def test_returns_none_when_ffmpeg_fails():
    with patch("audio.tts.prep", return_value="hello"), \
         patch("audio.tts.cfg"), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("subprocess.run") as mock_run, \
         patch("os.path.getsize", return_value=100), \
         patch("os.path.exists", return_value=True), \
         patch("os.remove"):
        mock_ntf.return_value.__enter__.return_value.name = "/tmp/fake.wav"
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1),
        ]
        from audio.tts import piper_to_pcm
        assert piper_to_pcm("hello") is None


def test_returns_none_when_piper_executable_missing():
    with patch("audio.tts.prep", return_value="hello"), \
         patch("audio.tts.cfg"), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("subprocess.run", side_effect=FileNotFoundError("piper not found")), \
         patch("os.path.exists", return_value=True), \
         patch("os.remove"):
        mock_ntf.return_value.__enter__.return_value.name = "/tmp/fake.wav"
        from audio.tts import piper_to_pcm
        assert piper_to_pcm("hello") is None
