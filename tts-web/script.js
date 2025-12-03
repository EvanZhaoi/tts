const textInput = document.getElementById("text-input");
const generateBtn = document.getElementById("generate");
const rateInput = document.getElementById("rate");
const volumeInput = document.getElementById("volume");
const langSelect = document.getElementById("lang");
const errorMsg = document.getElementById("error-msg");
const downloadLink = document.getElementById("download-link");

const API_BASE = "http://127.0.0.1:8000";

async function generate() {
  const text = textInput.value.trim();
  errorMsg.hidden = true;
  errorMsg.textContent = "";
  downloadLink.hidden = true;
  downloadLink.href = "#";

  if (!text) {
    errorMsg.hidden = false;
    errorMsg.textContent = "请输入要转换的文本";
    return;
  }

  generateBtn.disabled = true;
  generateBtn.textContent = "生成中...";

  try {
    const res = await fetch(`${API_BASE}/api/tts`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        lang: langSelect.value,
      }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const msg = data.detail || `生成失败，状态码：${res.status}`;
      throw new Error(msg);
    }

    const data = await res.json();
    const filename = data.file;
    downloadLink.href = `${API_BASE}/api/tts/${encodeURIComponent(filename)}`;
    downloadLink.hidden = false;
  } catch (err) {
    errorMsg.hidden = false;
    errorMsg.textContent = err.message || "生成语音失败，请稍后重试";
  } finally {
    generateBtn.disabled = false;
    generateBtn.textContent = "生成语音";
  }
}

generateBtn.addEventListener("click", generate);
