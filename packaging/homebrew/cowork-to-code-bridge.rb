class CoworkToCodeBridge < Formula
  desc "Connect Claude Cowork to Claude Code on your Mac via a safe file-based bridge"
  homepage "https://github.com/abhinaykrupa/cowork-to-code-bridge"
  url "https://github.com/abhinaykrupa/cowork-to-code-bridge/archive/refs/tags/v0.6.2.tar.gz"
  sha256 "728ae1668af2c5ca0246a4f075eebe9d46514ffc4860d47550bfe4dee4cb8861"
  license "MIT"

  depends_on :macos
  depends_on "python@3.12"

  def install
    libexec.install Dir["*"]
    # Setup is a separate, explicit step: it registers a launchd agent and writes
    # to ~/.cowork-to-code-bridge, which a formula must not do during install.
    # install.sh installs the Python package from this same bundled tree, so
    # the version always matches the formula.
    (bin/"cowork-to-code-bridge-setup").write_env_script(
      libexec/"install.sh",
      PATH:                      "#{formula_opt_bin("python@3.12")}:$PATH",
      BRIDGE_PYTHON_AUTOINSTALL: "0",
      BRIDGE_CLAUDE_AUTOINSTALL: "0",
    )
  end

  def caveats
    <<~EOS
      Finish setup (registers a launchd helper under ~/.cowork-to-code-bridge
      and prints a connect line to paste into Cowork):

        cowork-to-code-bridge-setup

      Uninstall: cowork-to-code-bridge-uninstall, then brew uninstall cowork-to-code-bridge
    EOS
  end

  test do
    assert_path_exists libexec/"install.sh"
    assert_path_exists libexec/"cowork_to_code_bridge/daemon.py"
    assert_predicate bin/"cowork-to-code-bridge-setup", :executable?
    # The bundled package imports and reports the formula's version.
    ver = shell_output("#{formula_opt_bin("python@3.12")}/python3.12 -c " \
                       "'import sys; sys.path.insert(0, \"#{libexec}\"); " \
                       "import cowork_to_code_bridge as m; print(m.__version__)'")
    assert_equal version.to_s, ver.strip
  end
end
