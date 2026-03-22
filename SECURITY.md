# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in BenchForge, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

### How to Report

1. **Email**: Send a detailed report to the maintainer via GitHub private vulnerability reporting.
2. **GitHub Security Advisory**: Use [GitHub's private vulnerability reporting](https://github.com/yeongseon/benchforge/security/advisories/new) to submit a report directly.

### What to Include

- Description of the vulnerability
- Steps to reproduce the issue
- Potential impact assessment
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours of receiving the report
- **Initial Assessment**: Within 5 business days
- **Fix Timeline**: Security patches will be prioritized and released as soon as practically possible

### Scope

BenchForge is a benchmarking tool that executes SQL queries against databases. Security considerations include:

- **SQL Injection**: BenchForge executes user-defined SQL queries by design. Users are responsible for running BenchForge only against test/benchmark databases, never against production systems with sensitive data.
- **DSN Handling**: Database connection strings may contain credentials. BenchForge redacts DSNs in result files, but users should avoid committing scenario files containing plaintext credentials.
- **Dependency Security**: We use Dependabot to monitor and update dependencies with known vulnerabilities.

### Disclosure Policy

- We follow [coordinated vulnerability disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure).
- Security issues will be disclosed publicly after a fix is available, with credit to the reporter (unless anonymity is requested).

## Best Practices for Users

1. **Never run BenchForge against production databases** with real user data.
2. **Use environment variables** for DSNs instead of hardcoding credentials in scenario files.
3. **Review scenario files** before execution — BenchForge runs arbitrary SQL as defined in scenarios.
4. **Keep BenchForge updated** to benefit from security patches.
