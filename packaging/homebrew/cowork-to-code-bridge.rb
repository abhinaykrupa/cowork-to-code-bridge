class CoworkToCodeBridge < Formula
  desc "Connect Claude Cowork to Claude Code on your Mac via a safe file-based bridge"
  homepage "https://github.com/abhinaykrupa/cowork-to-code-bridge"
  url "https://github.com/abhinaykrupa/cowork-to-code-bridge/archive/refs/tags/v0.5.0.tar.gz"
  sha256 "b2e1baa3343716f92bf0f4d7903af62811449231ec11d68d4b184b0068502c71"
  license "MIT"
  version "0.5.0"

  depends_on :macos
  depends_on "openssl@3"
  depends_on "python@3.12"

  def install
    libexec.install Dir["*"]
  end

  def post_install
    ENV["BRIDGE_PYTHON_AUTOINSTALL"] = "0"
    ENV["BRIDGE_CLAUDE_AUTOINSTALL"] = "0"
    ENV["HOMEBREW_NO_ENV_FILTERING"] = "1"
    py_bin = Formula["python@3.12"].opt_bin
    openssl_bin = Formula["openssl@3"].opt_bin
    ENV["PATH"] = "#{py_bin}:#{openssl_bin}:#{ENV["PATH"]}"
    system "/bin/bash", libexec/"install.sh"
  end

  def caveats
    <<~EOS
      cowork-to-code-bridge installs into ~/.cowork-to-code-bridge/ and registers
      a launchd helper. The installer prints a Cowork connect line — paste it
      into your next Cowork chat.

      Uninstall: cowork-to-code-bridge-uninstall
      (or: curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/daemon/uninstall.sh | bash)
    EOS
  end

  test do
    assert_predicate libexec/"install.sh", :exist?
    assert_predicate libexec/"install.sh", :executable?
  end
end
