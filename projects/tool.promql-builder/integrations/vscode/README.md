# PromQL+ VSCode Extension

Quick and simple syntax highlighting for PromQL+ files.

## Installation

1. Copy this directory to your VSCode extensions folder:
   ```bash
   # macOS/Linux
   cp -r integrations/vscode ~/.vscode/extensions/promql-plus

   # Windows
   xcopy /E /I integrations\vscode %USERPROFILE%\.vscode\extensions\promql-plus
   ```

2. Reload VSCode (or run "Developer: Reload Window" from command palette)

## Features

- Syntax highlighting for PromQL+ language
- Support for `.promql` and `.pql` file extensions
- **Markdown code block support** - use ` ```promql+ ` in your READMEs
- Comments with `#`
- Sugar functions: `~rate`, `~sum`, `~avg`, etc.
- Binary operation functions: `:div`, `:mul`, `:add`, etc.
- Pipeline definitions with `let` keyword
- Aliases and references: `$alias`
- Metric selectors: `{job="api"}`
- Duration literals: `5m`, `1h`, `30s`

## File Associations

The extension automatically highlights:
- `.promql` and `.pql` files
- Markdown code blocks tagged with `promql+` or `promql-plus`

You can also manually set the language mode by clicking the language indicator in the status bar and selecting "PromQL+".

## Markdown Support

In your README files, use code blocks with the `promql+` tag:

````markdown
```promql-plus
let base = http_requests_total;
$base | $[5m] | ~rate | ~sum<by(job)>
```
````

The syntax highlighting will automatically work in VSCode's markdown preview and editor.

## Example

```promql-plus
# Calculate error rate percentage
let errors = http_errors_total{job="api"};
let requests = http_requests_total{job="api"};
let common_ops = $[5m] | ~rate | ~sum<by(service)>;

let err_rate = $errors | $common_ops;
let req_rate = $requests | $common_ops;

$err_rate | :div<on(service)>($req_rate) | :mul(100)
```
