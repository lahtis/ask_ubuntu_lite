# ASK Ubuntu Lite

* **Author:** Tuomas Lähteenmäki
* **License:** GPLv3
* **Version:** 0.2.0
* **Type:** Local Linux assistant

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/License-GPLv3-green)
![Status](https://img.shields.io/badge/Status-Beta-yellow)

---

## Primary Links

* **Canonical Repository (Codeberg):** https://codeberg.org/lahtis/ask_ubuntu_lite
* **GitHub Mirror:** https://github.com/lahtis/ask_ubuntu_lite
* **Documentation:** https://codeberg.org/lahtis/ask_ubuntu_lite/src/branch/main/docs

---

## Overview

ASK Ubuntu Lite is a lightweight local assistant for Ubuntu Linux.

It helps users understand Linux commands, inspect the local system, and perform selected system operations through a controlled set of tools.

ASK Ubuntu Lite uses a language model provided through Ollama. System operations are performed through a controlled tool interface rather than through unrestricted shell access.

The project is designed to remain lightweight. It does not require a web server or a large application framework.

---

## Requirements

* Python 3.8 or newer
* Ollama must be installed and running.
* Ollama may run on the local system or on another machine accessible over the network.
* A compatible Ollama model must be available to ASK Ubuntu Lite.
* `self-healing-localization` is installed as a Python dependency.

Ollama is an external system dependency and is not installed by `pip`.

ASK Ubuntu Lite communicates with Ollama through its API.

---

## Installation

Clone the repository:

```bash
git clone https://codeberg.org/lahtis/ask_ubuntu_lite.git
cd ask_ubuntu_lite
```

Create and activate a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install ASK Ubuntu Lite and its Python dependencies:

```bash
pip install -e .
```

The project uses Self-Healing Localization (SHL) as a Python dependency.

---

## Configuration

ASK Ubuntu Lite creates its configuration directory and configuration files automatically when the application is first started.

The configuration is stored in:

```text
~/.config/ask-ubuntu-mini/
```

The main configuration file is:

```text
~/.config/ask-ubuntu-mini/config.toml
```

All ASK Ubuntu Lite settings are stored in `config.toml`, including the Ollama connection settings and the model names used by the application.

The configuration can point to an Ollama instance running either on the local system or on another machine accessible over the network.

You normally do not need to create `config.toml` manually. Start ASK Ubuntu Lite once and the configuration file will be created automatically. After that, you can edit the file to change the settings.

### System Prompt

The system prompt and its rules are configured in:

```text
~/.config/ask-ubuntu-mini/core.toml
```

If you want to modify the system prompt or its rules, edit `core.toml` manually.

Changes to `core.toml` are applied automatically through hot reload. The daemon does not need to be restarted after modifying the file.

---

## Ollama

ASK Ubuntu Lite uses Ollama to provide the language model.

Ollama can run either:

* on the same system as ASK Ubuntu Lite, or
* on another machine accessible over the network.

Install Ollama according to the official Ollama documentation and make sure the Ollama service is running.

The Ollama connection and model names are configured in:

```text
~/.config/ask-ubuntu-mini/config.toml
```

The required model must be available in the configured Ollama instance.

For a local Ollama installation, a model can be downloaded with:

```bash
ollama pull <model>
```

Replace `<model>` with the model name specified in your `config.toml`.

---

## Starting the Daemon

Start the ASK Ubuntu Lite daemon with:

```bash
python3 -m daemon
```

The daemon provides the background service used by the ASK Ubuntu Lite client.

---

## Starting ASK Ubuntu Lite

With the daemon running, start the client with:

```bash
python3 -m cli
```

You can then interact with ASK Ubuntu Lite from the terminal.

---

## Architecture

ASK Ubuntu Lite consists of a local client, a daemon, an Ollama-provided language model, and a controlled collection of system tools.

The general flow is:

```text
User
  |
  v
ASK Ubuntu Lite CLI
  |
  v
Daemon
  |
  v
Ollama
  |
  v
Language Model
  |
  v
Controlled Tools
  |
  v
Ubuntu System
```

Ollama may run locally or on another machine accessible over the network.

The tool interface limits which system operations the language model can request and allows the daemon to validate tool arguments before execution.

---

## Self-Healing Localization

ASK Ubuntu Lite uses **Self-Healing Localization (SHL)** for localization-related functionality.

SHL is maintained as a separate project and is installed as a Python dependency of ASK Ubuntu Lite.

---

## License

ASK Ubuntu Lite is licensed under the GNU General Public License version 3 (GPLv3).

See the `LICENSE` file for the complete license text.

The official GPLv3 license text is available from the Free Software Foundation:

https://www.gnu.org/licenses/gpl-3.0.html

