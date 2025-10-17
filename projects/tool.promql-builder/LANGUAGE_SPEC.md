# PromQL+ Language Specification

## Overview

**PromQL+** is a superset of PromQL (Prometheus Query Language) that adds:
- **Aliases** for reusable query fragments
- **Pipeline operators** for chaining transformations
- **Sugar syntax** for cleaner, more readable queries
- **Extended aggregation syntax** with templates
- **Binary operation functions** for explicit vector matching

PromQL+ compiles to standard PromQL, making it compatible with all Prometheus servers.

---

## 1. Lexical Structure

### 1.1 Whitespace and Comments

```promql+
# This is a comment
metric_name | ~rate  # inline comment
```

- **Whitespace**: spaces, tabs, newlines, and carriage returns are ignored
- **Comments**: Prometheus-style line comments starting with `#`

### 1.2 Identifiers

```
identifier ::= [a-zA-Z_][a-zA-Z0-9_]*
```

Examples: `http_requests_total`, `my_metric`, `_internal`

### 1.3 Numbers

```
number ::= [0-9]+ ("." [0-9]+)?
```

Examples: `5`, `3.14`, `0.99`, `1000`

### 1.4 Durations

```
duration ::= [0-9]+ time_unit
time_unit ::= "ms" | "s" | "m" | "h" | "d" | "w" | "y"
```

Examples: `5m`, `1h`, `30s`, `7d`

### 1.5 String Literals

```
string_literal ::= '"' [^"]* '"'
```

Examples: `"value"`, `"api-server"`, `".*prod.*"`

---

## 2. Aliases

Aliases allow you to define reusable query fragments, making complex queries more readable and maintainable.

### 2.1 Syntax

```promql+
let <identifier> = <expression>;
```

### 2.2 Usage

Aliases are referenced using the `$` prefix:

```promql+
let base = http_requests_total;
$base | $[5m] | ~rate
```

**Compiles to:**
```promql
rate(http_requests_total[5m])
```

### 2.3 Multiple Aliases

Multiple aliases can be defined in sequence:

```promql+
let base = http_requests_total{job="api"};
let ranged = $base | $[5m];
let rated = $ranged | #~rate;
$rated | sum by(method) $
```

**Compiles to:**
```promql
sum by(method) (rate(http_requests_total{job="api"}[5m]))
```

### 2.4 Deferred Pipeline Templates

Aliases store **unevaluated expressions** that are only evaluated when referenced. This enables powerful pipeline templates that can be reused with different inputs.

#### Using `$` as a Placeholder

When an alias contains a `$` placeholder, it represents "the value passed to this template":

```promql+
# Template with explicit placeholder
let common_ops = $[5m] | #~rate | #~sum<by(service)>;

let errors = http_errors_total{job="api"};
let requests = http_requests_total{job="api"};

let err_rate = $errors | $common_ops;
let req_rate = $requests | $common_ops;

$err_rate | :div($req_rate) | :mul(100)
```

**Compiles to:**
```promql
sum by(service) (rate(http_errors_total{job="api"}[5m])) /
sum by(service) (rate(http_requests_total{job="api"}[5m])) * 100
```

#### Implicit Placeholder in Sugar Functions

Sugar functions without explicit arguments automatically use the placeholder value when available:

```promql+
# Template with implicit placeholder
let common_ops = #~rate | #~sum<by(service)>;

let errors = http_errors_total{job="api"};
$errors | $common_ops
```

**Compiles to:**
```promql
sum by(service) (rate(http_errors_total{job="api"}))
```

When `$errors` is piped to `$common_ops`, the `#~rate` function receives `http_errors_total{job="api"}` as its input.

#### Mixed Syntax Templates

Templates can combine explicit `$` placeholders with standard PromQL syntax:

```promql+
# Standard PromQL syntax with $ placeholder
let ops_template = rate($) | sum by(service) $;

let metric = http_requests_total{job="api"};
$metric | $ops_template
```

**Compiles to:**
```promql
sum by(service) (rate(http_requests_total{job="api"}))
```

### 2.5 Alias Scope

- Aliases must be defined before they are referenced
- Aliases can reference previously defined aliases
- Aliases store raw, unevaluated expressions (lazy evaluation)
- Each alias definition must end with a semicolon (`;`)
- The final expression does not require a semicolon

---

## 3. Pipeline Operators

Pipelines allow you to chain transformations in a left-to-right flow, similar to Unix pipes or Flux.

### 3.1 Syntax

```promql+
<term> | <stage> | <stage> | ...
```

### 3.2 The Dollar Placeholder (`$`)

Within a pipeline, `$` represents the current expression being transformed.

```promql+
metric | $[5m] | rate($) | sum by(job) $
```

**Reading left-to-right:**
1. Start with `metric`
2. Apply range selector `[5m]` → `metric[5m]`
3. Apply `rate` function → `rate(metric[5m])`
4. Apply `sum by(job)` → `sum by(job) (rate(metric[5m]))`

### 3.3 Pipeline Stages

A stage can be:
- Range selector: `$[duration]`
- Subquery selector: `$[range:resolution]`
- Function call: `rate($)`, `topk($, 10)`
- Aggregation: `sum by(labels) $`
- Modifier: `$ offset duration`, `$ @ timestamp`
- Sugar function: `#~rate`, `#~offset(5m)`

---

## 4. Sugar Syntax

Sugar syntax provides cleaner alternatives to standard PromQL constructs.

### 4.1 Sugar Functions

Sugar functions are prefixed with `~` and can omit the `$` placeholder when used in pipelines.

#### Basic Syntax

```promql+
~<function_name>
~<function_name>(<args>)
~<function_name><template>
~<function_name><template>(<args>)
```

#### Examples

**Without arguments (implicit `$`):**
```promql+
metric | $[5m] | #~rate
# Compiles to: rate(metric[5m])
```

**With arguments:**
```promql+
metric | $[5m] | #~rate | #~topk(5)
# Compiles to: topk(5, rate(metric[5m]))
```

**With aggregation template:**
```promql+
metric | $[5m] | #~rate | #~sum<by(job, instance)>
# Compiles to: sum by(job, instance) (rate(metric[5m]))
```

**Combined:**
```promql+
metric | $[5m] | #~rate | #~bottomk<wo(job)>(5)
# Compiles to: bottomk without(job) (5, rate(metric[5m]))
```

**With immediate resampling:**
```promql+
metric | $[5m] | #~rate[5m:]
# Compiles to: (rate(metric[5m]))[5m:]

metric | $[5m] | #~rate[10m:1m]
# Compiles to: (rate(metric[5m]))[10m:1m]

metric | $[5m] | #~sum<by(service)>[5m:]
# Compiles to: (sum by(service) (metric[5m]))[5m:]
```

Sugar functions and aggregations with templates can have **immediate resampling** by appending a range or subquery selector `[range:resolution]`. This applies the resampling directly to the function result.

### 4.2 Aggregation Templates

Aggregation templates are specified in angle brackets `<>` and support:

- `<by(labels)>` - group by specified labels
- `<without(labels)>` - group by all labels except specified
- `<wo(labels)>` - shorthand for `without`

**Examples:**
```promql+
metric | $[5m] | #~rate | #~sum<by(instance, job)>
# Compiles to: sum by(instance, job) (rate(metric[5m]))

metric | $[5m] | #~rate | #~avg<without(pod)>
# Compiles to: avg without(pod) (rate(metric[5m]))

metric | $[5m] | #~rate | #~max<wo(instance)>
# Compiles to: max without(instance) (rate(metric[5m]))
```

### 4.3 Built-in Sugar Functions

#### Modifiers

| Sugar Syntax | Equivalent | Description |
|-------------|------------|-------------|
| `#~offset(duration)` | `$ offset duration` | Time offset |
| `#~at(timestamp)` | `$ @ timestamp` | Evaluate at timestamp |
| `#~at_start` | `$ @ start()` | Evaluate at query start |
| `#~at_end` | `$ @ end()` | Evaluate at query end |

**Examples:**
```promql+
metric | #~offset(5m)
# Compiles to: metric offset 5m

metric | $[5m] | #~at_end
# Compiles to: metric[5m] @ end()
```

#### Subquery Resampling

| Sugar Syntax | Equivalent | Description |
|-------------|------------|-------------|
| `#~resample(range)` | `$[range:range]` | Resample with same resolution |
| `#~resample(range, resolution)` | `$[range:resolution]` | Resample with custom resolution |

**Examples:**
```promql+
metric | $[5m] | #~rate | #~resample(1m)
# Compiles to: (rate(metric[5m]))[1m:1m]

metric | $[5m] | #~rate | #~resample(10m, 1m)
# Compiles to: (rate(metric[5m]))[10m:1m]
```

#### Any PromQL Function

Sugar syntax works with any PromQL function. The current expression (implicit `$`) is always passed as the **last** argument:

```promql+
metric | $[5m] | #~rate | #~round | #~clamp_max(100)
# Compiles to: clamp_max(round(rate(metric[5m])), 100)

metric | $[5m] | #~rate | #~topk(10)
# Compiles to: topk(10, rate(metric[5m]))

metric | $[5m] | #~rate | #~quantile(0.95)
# Compiles to: quantile(0.95, rate(metric[5m]))
```

**Parameter Order Rules:**
- Sugar functions without explicit `$` placeholder insert the current expression as the **last argument**
- This matches PromQL conventions where aggregation functions like `topk(k, vector)` and `quantile(q, vector)` take parameters first, vector last
- Functions like `clamp_max(vector, max)` also follow this pattern in the sugar syntax: `#~clamp_max(100)` → `clamp_max(expr, 100)`

### 4.5 Binary Operation Functions

Binary operation functions provide an alternative syntax for arithmetic operations with vector matching modifiers. They use the `:` prefix.

#### Basic Syntax

```promql+
:<op_name>(<left>, <right>)
:<op_name><template>(<left>, <right>)
```

#### Available Operations

| Operation | Symbol | Function Form |
|-----------|--------|---------------|
| Addition | `+` | `:add` |
| Subtraction | `-` | `:sub` |
| Multiplication | `*` | `:mul` |
| Division | `/` | `:div` |
| Modulo | `%` | `:mod` |
| Exponentiation | `^` | `:pow` |

#### Template Modifiers

Binary operation functions support template modifiers in angle brackets `<>`:

- `<on(labels)>` - Match on specific labels
- `<ignoring(labels)>` - Ignore specific labels
- `<group_left>` or `<group_left(labels)>` - Many-to-one matching (left side is many)
- `<group_right>` or `<group_right(labels)>` - One-to-many matching (right side is many)

**Note:** `group_left` and `group_right` can be specified:
- Without parentheses: `group_left`, `group_right`
- With empty parentheses: `group_left()`, `group_right()`
- With labels: `group_left(label1, label2)`, `group_right(label1, label2)`

**Modifiers can be combined in any order:**

```promql+
:div<on(job, instance), group_left>(a, b)
:div<group_left, on(job, instance)>(a, b)  # same meaning
:div<on(job), group_left(region)>(a, b)    # with included labels
```

#### Two-Argument Form

Explicit specification of both operands:

```promql+
:div<on(service, env), group_left()>(requests, capacity)
# Compiles to: requests / on(service, env) group_left() capacity
```

#### Single-Argument Form (Pipeline)

When used in a pipeline, the left operand is implicit (the current expression):

```promql+
requests | :div<on(service)>(capacity)
# Compiles to: requests / on(service) capacity

metric_a | $[5m] | #~rate | :mul<ignoring(pod)>(metric_b)
# Compiles to: rate(metric_a[5m]) * ignoring(pod) metric_b
```

#### Immediate Resampling

Binary operations can have immediate resampling by appending a range or subquery selector:

```promql+
a | :div(b)[5m:]
# Compiles to: (a / b)[5m:]

a | :div<on(service)>(b)[10m:1m]
# Compiles to: (a / on(service) b)[10m:1m]

$rate_a | :add<on(job)>($rate_b)[5m:]
# Compiles to: (rate_a + on(job) rate_b)[5m:]
```

This applies the resampling directly to the result of the binary operation.

#### Examples

**Simple division without modifiers:**
```promql+
:div(errors, requests)
# Compiles to: errors / requests
```

**Division with label matching:**
```promql+
:div<on(service, env)>(errors, requests)
# Compiles to: errors / on(service, env) requests
```

**Many-to-one matching:**
```promql+
# Without labels in group_left
:div<on(job, instance), group_left>(requests, capacity)
# Compiles to: requests / on(job, instance) group_left capacity

# With labels in group_left
:div<on(job, instance), group_left(service)>(requests, capacity)
# Compiles to: requests / on(job, instance) group_left(service) capacity
```

**In a pipeline:**
```promql+
let err_rate = errors | $[5m] | #~rate | #~sum<by(service, env)>;
let req_rate = requests | $[5m] | #~rate | #~sum<by(service, env)>;
$err_rate | :div($req_rate) | :mul(100)
# Compiles to: err_rate / req_rate * 100
```

**Complex example with all features:**
```promql+
let requests = http_requests | $[5m] | #~rate | #~sum<by(service, env)>;
let capacity = service_capacity{type="max"};

# Using group_left without parentheses
$requests | :div<on(service, env), group_left>($capacity)
# Compiles to: sum by(service, env) (rate(http_requests[5m])) / 
#              on(service, env) group_left service_capacity{type="max"}

# Or with included labels
$requests | :div<on(service, env), group_left(region)>($capacity)
# Compiles to: sum by(service, env) (rate(http_requests[5m])) / 
#              on(service, env) group_left(region) service_capacity{type="max"}
```

#### When to Use Binary Operation Functions

**Use binary operation functions when:**
- You need vector matching modifiers (`on`, `ignoring`, `group_left`, `group_right`)
- You want explicit, readable syntax for complex joins
- You're working in pipelines and want to maintain left-to-right flow

**Use standard infix operators when:**
- Doing simple arithmetic without modifiers: `a + b`, `a * 100`
- Maintaining compatibility with existing PromQL queries
- The operation is straightforward and doesn't need special matching

---

## 5. Expressions

### 5.1 Terms

A term is the basic building block of expressions:

- **Number**: `5`, `3.14`, `0.99`
- **Identifier**: `metric_name`
- **Reference**: `$alias`
- **Metric selector**: `{job="api"}`
- **Metric with labels**: `http_requests{job="api"}`
- **Parenthesized expression**: `(expr + expr)`
- **Function call**: `rate(expr)`
- **Aggregation**: `sum by(job) (expr)`
- **Sugar function**: `#~rate`, `#~sum<by(job)>`
- **Binary operation function**: `:div<on(job)>(a, b)`, `:add(a, b)`

### 5.2 Postfix Selectors

Terms can have postfix selectors:

- **Range selector**: `metric[5m]`
- **Subquery**: `expr[5m:1m]`

These can be combined:
```promql+
$alias[5m]
# References alias and adds range selector
```

### 5.3 Arithmetic Expressions

Standard PromQL arithmetic operators:

- `+` - Addition
- `-` - Subtraction
- `*` - Multiplication
- `/` - Division
- `%` - Modulo
- `^` - Exponentiation

**Examples:**
```promql+
let alias1 = metric1 | $[5m] | #~rate;
let alias2 = metric2 | $[5m] | #~rate;
$alias1 + $alias2
# Compiles to: rate(metric1[5m]) + rate(metric2[5m])
```

### 5.4 Binary Operator Modifiers

Binary operators support PromQL matching modifiers for controlling label matching behavior in vector operations.

#### Infix Syntax (Standard PromQL)

```promql+
expr1 on(label1, label2) expr2
expr1 ignoring(label1, label2) expr2
expr1 on(labels) group_left expr2
expr1 on(labels) group_left() expr2
expr1 on(labels) group_left(label1, label2) expr2
expr1 on(labels) group_right expr2
```

**Note:** `group_left` and `group_right` can be specified without parentheses, with empty parentheses, or with labels in parentheses.

**Example:**
```promql+
let a = metric_a | $[5m] | #~rate;
let b = metric_b | $[5m] | #~rate;
$a / on(job, instance) group_left $b
```

#### Function Syntax (PromQL+ Extension)

Binary operation functions (see Section 4.5) provide an alternative, more explicit syntax:

```promql+
:div<on(job, instance), group_left>(a, b)
# Equivalent to: a / on(job, instance) group_left b
```

**Both forms are supported and compile to identical PromQL output.** Choose based on:
- **Infix**: Familiar PromQL syntax, good for simple operations
- **Function**: More explicit, better for pipelines and complex matching

---

## 6. Aggregations

### 6.1 Standard Aggregations

PromQL+ supports all standard PromQL aggregation operators:

- `sum` - Sum of values
- `avg` - Average of values
- `min` - Minimum value
- `max` - Maximum value
- `count` - Count of elements
- `stddev` - Standard deviation
- `stdvar` - Standard variance
- `topk` - Top K elements
- `bottomk` - Bottom K elements
- `quantile` - Calculate quantile
- `count_values` - Count unique values
- `group` - Group series

### 6.2 Pipeline Aggregation Syntax

```promql+
<agg_op> by(<labels>) $
<agg_op> without(<labels>) $
```

**Examples:**
```promql+
metric | $[5m] | rate($) | sum by(job, instance) $
# Compiles to: sum by(job, instance) (rate(metric[5m]))

metric | $[5m] | rate($) | avg without(pod) $
# Compiles to: avg without(pod) (rate(metric[5m]))
```

### 6.3 Standard PromQL Aggregation Syntax

Standard PromQL aggregation syntax is also supported:

```promql+
sum by(job) (rate(metric[5m]))
avg without(instance) (rate(metric[5m]))
```

### 6.4 Aggregations with Parameters

Some aggregations require parameters. In PromQL, these functions take parameters first and the vector last:

```promql+
metric | $[5m] | rate($) | topk($, 10)
# Compiles to: topk(10, rate(metric[5m]))

metric | $[5m] | rate($) | quantile($, 0.95)
# Compiles to: quantile(0.95, rate(metric[5m]))

metric | $[5m] | rate($) | bottomk($, 5)
# Compiles to: bottomk(5, rate(metric[5m]))
```

**Note:** When using the sugar syntax without explicit `$`, parameters still come first:

```promql+
metric | $[5m] | #~rate | #~topk(10)
# Compiles to: topk(10, rate(metric[5m]))
```

---

## 7. Selectors

### 7.1 Range Selectors

Select time series over a range:

```promql+
$[duration]
```

**Examples:**
```promql+
metric | $[5m]
# Compiles to: metric[5m]
```

### 7.2 Subquery Selectors

Execute a query over a range with specific resolution:

```promql+
$[range:resolution]
$[range:]  # empty resolution
```

**Examples:**
```promql+
metric | $[5m] | rate($) | $[10m:1m]
# Compiles to: (rate(metric[5m]))[10m:1m]

metric | $[5m] | rate($) | $[10m:]
# Compiles to: (rate(metric[5m]))[10m:]
```

### 7.3 Metric Selectors

Select metrics by labels:

```promql+
{label="value"}
{label=~"regex"}
{label!="value"}
{label!~"regex"}
```

**Examples:**
```promql+
{job="api"} | $[5m] | rate($)
# Compiles to: rate({job="api"}[5m])

http_requests{job="api", status="200"} | $[5m] | rate($)
# Compiles to: rate(http_requests{job="api",status="200"}[5m])
```

---

## 8. Modifiers

### 8.1 Offset Modifier

Shift the time window:

**Pipeline syntax:**
```promql+
$ offset <duration>
```

**Sugar syntax:**
```promql+
#~offset(<duration>)
```

**Examples:**
```promql+
metric | $ offset 5m
# Compiles to: metric offset 5m

metric | #~offset(5m)
# Compiles to: metric offset 5m
```

### 8.2 @ Timestamp Modifier

Evaluate at a specific timestamp:

**Pipeline syntax:**
```promql+
$ @ <timestamp>
$ @ start()
$ @ end()
```

**Sugar syntax:**
```promql+
#~at(<timestamp>)
#~at_start
#~at_end
```

**Examples:**
```promql+
metric | $ @ 1234567890
# Compiles to: metric @ 1234567890

metric | #~at_end
# Compiles to: metric @ end()
```

### 8.3 Combined Modifiers

Modifiers can be chained:

```promql+
metric | $[5m] | $ offset 5m | $ @ end()
# Compiles to: metric[5m] offset 5m @ end()

metric | $[5m] | #~offset(5m) | #~at_end
# Compiles to: metric[5m] offset 5m @ end()
```

---

## 9. Complete Examples

### 9.1 Simple Rate Query

```promql+
http_requests_total | $[5m] | #~rate
```

**Compiles to:**
```promql
rate(http_requests_total[5m])
```

### 9.2 Aggregated Rate Query

```promql+
http_requests_total | $[5m] | #~rate | #~sum<by(job, method)>
```

**Compiles to:**
```promql
sum by(job, method) (rate(http_requests_total[5m]))
```

### 9.3 Complex Query with Aliases

```promql+
# Define base metrics
let requests = http_requests_total{job="api"};
let errors = http_errors_total{job="api"};

# Calculate rates
let req_rate = $requests | $[5m] | #~rate | #~sum<by(service)>;
let err_rate = $errors | $[5m] | #~rate | #~sum<by(service)>;

# Calculate error ratio
$err_rate / $req_rate * 100
```

**Compiles to:**
```promql
sum by(service) (rate(http_errors_total{job="api"}[5m])) /
sum by(service) (rate(http_requests_total{job="api"}[5m])) * 100
```

### 9.4 Histogram Quantile with Subqueries

```promql+
# Build histogram quantile step by step
let base = http_duration_bucket{job="api"};
let increased = $base | $[5m] | increase($) | avg by(le, service) $;
let subquery = $increased | $[15m:30s] | rate($) | sum by(le, service) $;

# Calculate 99th percentile
histogram_quantile(0.99, $subquery)
```

**Compiles to:**
```promql
histogram_quantile(0.99,
  sum by(le, service) (
    rate(
      (avg by(le, service) (
        increase(http_duration_bucket{job="api"}[5m])
      ))[15m:30s]
    )
  )
)
```

### 9.5 Binary Operation with Modifiers

```promql+
let requests = http_requests | $[5m] | #~rate | #~sum<by(service, env)>;
let capacity = service_capacity;

$requests / on(service, env) group_left $capacity
```

**Compiles to:**
```promql
sum by(service, env) (rate(http_requests[5m])) /
on(service, env) group_left service_capacity
```

### 9.6 Chained Sugar Functions

```promql+
metric | $[5m] | #~rate | #~offset(5m) | #~at_end | #~round | #~clamp_max(100)
```

**Compiles to:**
```promql
clamp_max(round(rate(metric[5m]) offset 5m @ end()), 100)
```

### 9.7 Pipeline Templates with Resampling

```promql+
# Define reusable pipeline templates
let common_ops_1 = #~rate | #~sum<by(service)>;
let common_ops_2 = $[5m] | #~rate | #~sum<by(service)>;
let common_ops_3 = rate($) | sum by(service) $;

# Apply templates to different metrics
let errors = http_errors_total{job="api"};
let requests = http_requests_total{job="api"};

let err_rate = $errors | $common_ops_1;
let req_rate = $requests | $common_ops_2;

# Calculate percentage with immediate resampling
($err_rate | :div<on(service)>($req_rate)[5m:] | :mul(100))[10m:1m]
```

**Compiles to:**
```promql
(((sum by(service) (rate(http_errors_total{job="api"})) /
   on(service) sum by(service) (rate(http_requests_total{job="api"}[5m])))[5m:] * 100))[10m:1m]
```

This example demonstrates:
- **Three template variations**: implicit placeholder, explicit `$[5m]`, and standard PromQL syntax
- **Template reuse**: applying `common_ops` to different metrics
- **Immediate resampling**: `[5m:]` on the division result
- **Nested resampling**: `[10m:1m]` on the final result

### 9.8 Immediate Resampling Examples

```promql+
# Simple rate with resampling
metric | $[5m] | #~rate[5m:]
# Compiles to: (rate(metric[5m]))[5m:]

# Aggregation with resampling
metric | $[5m] | #~rate | #~sum<by(service)>[10m:1m]
# Compiles to: (sum by(service) (rate(metric[5m])))[10m:1m]

# Binary operation with resampling
let a = metric_a | $[5m] | #~rate;
let b = metric_b | $[5m] | #~rate;
$a | :div<on(job)>($b)[5m:]
# Compiles to: (rate(metric_a[5m]) / on(job) rate(metric_b[5m]))[5m:]
```

---

## 10. Grammar Summary

```ebnf
query          ::= (alias ";")* expression

alias          ::= "let" identifier "=" expression

expression     ::= pipeline | arithmetic | term

pipeline       ::= term ("|" stage)+

arithmetic     ::= term (binary_op binary_op_modifiers? term)+

binary_op      ::= "^" | "*" | "/" | "%" | "+" | "-"

stage          ::= range_selector
                 | subquery_selector
                 | offset_modifier
                 | at_modifier
                 | aggregation
                 | sugar_function
                 | function_call

term           ::= "(" expression ")"
                 | aggregation_term
                 | sugar_function_term
                 | function_call_term
                 | reference
                 | metric_with_labels
                 | metric_selector
                 | number
                 | identifier

reference      ::= "$" identifier?

range_selector ::= "$" "[" duration "]"

subquery_selector ::= "$" "[" duration ":" duration? "]"

postfix_selector ::= "[" duration "]"
                   | "[" duration ":" duration? "]"

sugar_function ::= "#" identifier aggregation_template? ("(" args ")")? postfix_selector?

binary_op_function ::= ":" binary_op_name binary_op_template? "(" expression ")" postfix_selector?

binary_op_template ::= "<" binary_op_modifier_item ("," binary_op_modifier_item)* ">"

binary_op_modifier_item ::= on_modifier | ignoring_modifier | group_left_modifier | group_right_modifier

aggregation_template ::= "<" (by_clause | without_clause | wo_clause) ">"

aggregation    ::= aggregation_op (by_clause | without_clause)? "$"
                 | aggregation_op (by_clause | without_clause)? "(" expression ")"

function_call  ::= identifier "(" args? ")"
```

---

## 11. Design Principles

1. **Backward Compatibility**: All valid PromQL queries are valid PromQL+
2. **Left-to-Right Flow**: Pipelines read naturally from left to right
3. **Readability**: Aliases and sugar syntax improve readability
4. **Composability**: Aliases enable query fragment reuse
5. **Explicit**: The `$` placeholder makes transformations explicit
6. **Flexible**: Mix standard PromQL and PromQL+ syntax as needed

---

## 12. Implementation Notes

### 12.1 Compilation

PromQL+ compiles to standard PromQL through the following transformations:

1. **Alias Resolution**: Replace all `$alias` references with their definitions
2. **Pipeline Expansion**: Expand pipelines from left to right, substituting `$`
3. **Sugar Desugaring**: Convert sugar functions to standard PromQL syntax
4. **Validation**: Ensure output is valid PromQL

### 12.2 Operator Precedence

1. Parentheses `()`
2. Postfix selectors `[...]`
3. Exponentiation `^`
4. Multiplication, Division, Modulo `*`, `/`, `%`
5. Addition, Subtraction `+`, `-`
6. Pipeline operator `|` (lowest precedence in expressions)

### 12.3 Type System

PromQL+ follows PromQL's type system:

- **Instant Vector**: Set of time series at a single timestamp
- **Range Vector**: Set of time series over a time range
- **Scalar**: Numeric value
- **String**: String value (limited use in PromQL)

Type conversions happen implicitly following PromQL rules.

---

## Version

This specification describes PromQL+ version 1.0.

