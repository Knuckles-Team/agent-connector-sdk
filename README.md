# agent-connector-sdk

[![GitHub Repo stars](https://img.shields.io/github/stars/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/forks)
[![GitHub contributors](https://img.shields.io/github/contributors/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/graphs/contributors)
[![GitHub license](https://img.shields.io/github/license/Knuckles-Team/agent-connector-sdk)](LICENSE)
[![GitHub last commit (by committer)](https://img.shields.io/github/last-commit/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/commits/main)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/pulls)
[![GitHub closed pull requests](https://img.shields.io/github/issues-pr-closed/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/pulls?q=is%3Apr+is%3Aclosed)
[![GitHub issues](https://img.shields.io/github/issues/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk/issues)
[![GitHub top language](https://img.shields.io/github/languages/top/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub language count](https://img.shields.io/github/languages/count/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub repo size](https://img.shields.io/github/repo-size/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![GitHub repo file count (file type)](https://img.shields.io/github/directory-file-count/Knuckles-Team/agent-connector-sdk)](https://github.com/Knuckles-Team/agent-connector-sdk)
[![PyPI - Version](https://img.shields.io/pypi/v/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - Downloads](https://img.shields.io/pypi/dd/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - License](https://img.shields.io/pypi/l/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![PyPI - Implementation](https://img.shields.io/pypi/implementation/agent-connector-sdk)](https://pypi.org/project/agent-connector-sdk/)
[![Build](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/release.yml/badge.svg)](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/release.yml)
[![Documentation](https://github.com/Knuckles-Team/agent-connector-sdk/actions/workflows/pages.yml/badge.svg)](https://knuckles-team.github.io/agent-connector-sdk/)

## Overview

The Agent Connector SDK provides a shared runtime for secure MCP connectors, source synchronization, and governed write-back. Connector packages supply vendor clients and domain tools; the SDK supplies common transport and lifecycle contracts.

*Version: 0.1.0*

## Key Capabilities

- Build MCP servers with authentication, visibility, health, and safe exposure policies.
- Serve connector skills, prompts, ontologies, shapes, and manifests as MCP content.
- Run source synchronization with bounded paging and receipt-gated checkpoints.
- Validate typed extensions and govern write-back with authorization and reconciliation.

The SDK depends directly on `epistemic-graph>=2.27.0`. Its generated
SourceIngest, ConnectorPack, and WriteBack models and clients are the sole
graph-boundary contracts; the SDK defines no parallel DTO, receipt, or digest.
The bundled sink reads EG's durable source status, commits record pages, and
imports independently identified connector content packs through those APIs.

## Documentation

Start at the [Agent Connector SDK documentation](https://knuckles-team.github.io/agent-connector-sdk/). See the [connector server guide](https://knuckles-team.github.io/agent-connector-sdk/connector-servers/), [source sync guide](https://knuckles-team.github.io/agent-connector-sdk/connector-sync/), and [extension ports](https://knuckles-team.github.io/agent-connector-sdk/extension-ports/).

## Architecture

Connector packages own vendor API clients and source effects. The SDK owns MCP lifecycle, credentials, paging, synchronization, and write-back contracts; epistemic-graph owns durable graph state, validation, reasoning, and receipts.

## Quick Start

Install the SDK and inspect the runner options. The [source sync guide](https://knuckles-team.github.io/agent-connector-sdk/connector-sync/) has a complete configuration example.

```bash
uvx --from agent-connector-sdk connector-sync --help
```

## Contributing

Issues and pull requests are welcome. Follow [AGENTS.md](AGENTS.md) for repository boundaries and validation requirements.

## License

Licensed under the [MIT License](LICENSE).
