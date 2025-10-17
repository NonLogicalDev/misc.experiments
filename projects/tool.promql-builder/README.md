# PromQL Builder

A Rust-based PromQL query builder with Flux-like syntax using the [Pest](https://github.com/pest-parser/pest) parser generator.

## Features

- **Pipe operators**: Chain transformations using `|`
- **Alias support**: Define and reuse query fragments with `alias = expr`
- **Variable substitution**: Use `$` to reference the current expression in pipelines
- **Range selectors**: `$[5m]` syntax for time ranges
- **Subqueries**: `$[5m:1m]` syntax for subquery ranges
- **Functions**: `rate($)`, `topk($, 10)`, etc.
- **Aggregations**: `sum by(labels) $`, `avg without(labels) $`
- **Modifiers**: `$ offset 5m`, `$ @ 1234567890`, `$ @ start()`, `$ @ end()`
- **Sugar syntax**: `#rate`, `#offset(5m)`, `#at(timestamp)`, `#at_start`, `#at_end`, `#resample(range[, resolution])`
- **Comments**: `-- comment text` (SQL-style line comments)
- **Arithmetic**: Binary operators (`+`, `-`, `*`, `/`, `%`, `^`) with parentheses support

## Syntax

### Basic Pipeline
```bash
{metric} | $[1m] | rate($) | sum by(le, method, path) $
```
Output: `sum by(le, method, path) (rate({metric}[1m]))`

### Aliases
Define reusable query fragments:
```bash
req = http_requests_total; $req | $[5m] | rate($)
```
Output: `rate(http_requests_total[5m])`

### Chained Aliases
```bash
base = http_requests_total; ranged = $base | $[5m]; $ranged | rate($) | sum by(job) $
```
Output: `sum by(job) (rate(http_requests_total[5m]))`

### Functions with Arguments
```bash
http_requests_total | $[5m] | rate($) | topk($, 10)
```
Output: `topk(rate(http_requests_total[5m]), 10)`

### Subqueries
```bash
http_requests_total | $[5m] | rate($) | avg without(instance) $ | $[1m:1m]
```
Output: `(avg without(instance) (rate(http_requests_total[5m])))[1m:1m]`

### Modifiers
```bash
http_requests_total | $[5m] | $ offset 5m | $ @ end()
```
Output: `http_requests_total[5m] offset 5m @ end()`

### Sugar Syntax
Alternative function-like syntax for modifiers (cleaner in some cases). Sugar functions assume `$` (current expression) as the first argument by default:
```bash
# Using #rate instead of rate($)
http_requests_total | $[5m] | #rate
# Output: rate(http_requests_total[5m])

# Using #offset(duration) instead of $ offset duration
http_requests_total | #offset(5m)
# Output: http_requests_total offset 5m

# Using #at_end instead of $ @ end()
http_requests_total | $[5m] | #at_end
# Output: http_requests_total[5m] @ end()

# Using #at(timestamp) instead of $ @ timestamp
http_requests_total | #at(1234567890)
# Output: http_requests_total @ 1234567890

# Using #resample(range[, resolution]) for subqueries
http_requests_total | $[5m] | #rate | #resample(1m)
# Output: (rate(http_requests_total[5m]))[1m:1m]

http_requests_total | $[5m] | #rate | #resample(10m, 1m)
# Output: (rate(http_requests_total[5m]))[10m:1m]
```

## Usage

### Build
```bash
cargo build --release
```

### Run
```bash
# From command line argument
./target/release/promql-builder 'http_requests_total | $[1m] | rate($)'

# From stdin
echo 'http_requests_total | $[5m] | rate($)' | ./target/release/promql-builder

# From file
./target/release/promql-builder < examples/example.txt
```

### Run Tests
```bash
cargo test
```

## Grammar

The parser is defined in `src/grammar.pest` using Pest PEG syntax:

- **Aliases**: `alias_name = expression`
- **References**: `$alias_name`
- **Pipelines**: `expr | stage1 | stage2`
- **Stages**: Range selectors, subqueries, modifiers, function calls, or aggregations
- **Variable substitution**: `$` represents current expression in pipelines

## Examples

```bash
# Simple metric
promql-builder 'http_requests_total'
# Output: http_requests_total

# With range selector
promql-builder 'http_requests_total | $[5m]'
# Output: http_requests_total[5m]

# With rate function
promql-builder 'http_requests_total | $[1m] | rate($)'
# Output: rate(http_requests_total[1m])

# With aggregation
promql-builder 'http_requests_total | $[1m] | rate($) | sum by(method) $'
# Output: sum by(method) (rate(http_requests_total[1m]))

# Metric selector
promql-builder '{job="api"} | $[1m] | rate($) | sum by(le, method, path) $'
# Output: sum by(le, method, path) (rate({job="api"}[1m]))

# Using aliases
promql-builder 'req = http_requests_total; $req | $[5m] | rate($)'
# Output: rate(http_requests_total[5m])

# Subqueries
promql-builder 'http_requests_total | $[5m] | rate($) | avg without(instance) $ | $[1m:1m]'
# Output: (avg without(instance) (rate(http_requests_total[5m])))[1m:1m]

# Offset modifier
promql-builder 'http_requests_total | $ offset 5m'
# Output: http_requests_total offset 5m

# @ timestamp modifier
promql-builder 'http_requests_total | $[5m] | $ @ 1234567890'
# Output: http_requests_total[5m] @ 1234567890

# Combined modifiers
promql-builder 'http_requests_total | $[5m] | $ offset 5m | $ @ end()'
# Output: http_requests_total[5m] offset 5m @ end()

# Sugar syntax - rate
promql-builder 'http_requests_total | $[5m] | #rate'
# Output: rate(http_requests_total[5m])

# Sugar syntax - offset
promql-builder 'http_requests_total | #offset(5m)'
# Output: http_requests_total offset 5m

# Sugar syntax - at_end
promql-builder 'http_requests_total | $[5m] | #at_end'
# Output: http_requests_total[5m] @ end()

# Sugar syntax - resample
promql-builder 'http_requests_total | $[5m] | #rate | #resample(1m)'
# Output: (rate(http_requests_total[5m]))[1m:1m]

# Sugar syntax - combined
promql-builder 'http_requests_total | $[5m] | #rate | #offset(5m) | #at_end'
# Output: rate(http_requests_total[5m]) offset 5m @ end()
```

## License

This project is for internal use.
