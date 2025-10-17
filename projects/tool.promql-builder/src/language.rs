use pest::Parser;
use pest_derive::Parser;
use std::collections::HashMap;

#[derive(Parser)]
#[grammar = "grammar.pest"]
pub struct PromQLParser;

pub struct PromQLBuilder {
    // Store raw unevaluated expressions
    aliases: HashMap<String, String>,
}

impl PromQLBuilder {
    pub fn new() -> Self {
        Self {
            aliases: HashMap::new(),
        }
    }

    pub fn build(&mut self, input: &str) -> Result<String, String> {
        let pairs = PromQLParser::parse(Rule::query, input)
            .map_err(|e| format!("Parse error: {}", e))?;

        let mut result = String::new();

        for pair in pairs {
            if pair.as_rule() == Rule::query {
                for inner_pair in pair.into_inner() {
                    match inner_pair.as_rule() {
                        Rule::alias => {
                            self.parse_alias(inner_pair)?;
                        }
                        Rule::expression => {
                            result = self.parse_expression(inner_pair)?;
                        }
                        Rule::EOI => {}
                        _ => {}
                    }
                }
            }
        }

        Ok(result)
    }

    fn parse_expression(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::pipeline => {
                    return self.parse_pipeline(inner);
                }
                Rule::arithmetic => {
                    return self.parse_arithmetic(inner);
                }
                Rule::term => {
                    return self.parse_term(inner);
                }
                _ => {}
            }
        }
        Ok(String::new())
    }

    fn parse_arithmetic(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut parts = Vec::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::term => {
                    parts.push(self.parse_term(inner)?);
                }
                Rule::binary_op => {
                    parts.push(format!(" {} ", inner.as_str()));
                }
                Rule::binary_op_modifiers => {
                    parts.push(format!(" {} ", self.parse_binary_op_modifiers(inner)?));
                }
                _ => {}
            }
        }

        Ok(parts.join(""))
    }

    fn parse_binary_op_modifiers(&self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut result = Vec::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::on_modifier => {
                    let labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                    result.push(format!("on({})", labels));
                }
                Rule::ignoring_modifier => {
                    let labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                    result.push(format!("ignoring({})", labels));
                }
                Rule::group_modifier => {
                    result.push(self.parse_group_modifier(inner)?);
                }
                _ => {}
            }
        }

        Ok(result.join(" "))
    }

    fn parse_group_modifier(&self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut modifier_type = String::new();
        let mut labels = Vec::new();

        let text = pair.as_str();
        if text.starts_with("group_left") {
            modifier_type = "group_left".to_string();
        } else if text.starts_with("group_right") {
            modifier_type = "group_right".to_string();
        }

        // Check if parentheses are present in the original text
        let has_parens = text.contains('(');

        // Check if there are labels
        for inner in pair.into_inner() {
            if inner.as_rule() == Rule::label_list {
                labels = inner
                    .into_inner()
                    .map(|p| p.as_str())
                    .collect::<Vec<_>>();
            }
        }

        if !has_parens {
            // No parentheses at all - just return the modifier
            Ok(modifier_type)
        } else if labels.is_empty() {
            // Empty parentheses
            Ok(format!("{}()", modifier_type))
        } else {
            // Parentheses with labels
            Ok(format!("{}({})", modifier_type, labels.join(", ")))
        }
    }

    fn parse_aggregation_term(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut agg_op = String::new();
        let mut clause_type = String::new();
        let mut labels = String::new();
        let mut expr = String::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::aggregation_op => {
                    agg_op = inner.as_str().to_string();
                }
                Rule::by_clause => {
                    clause_type = "by".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                Rule::without_clause => {
                    clause_type = "without".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                Rule::expression => {
                    expr = self.parse_expression(inner)?;
                }
                _ => {}
            }
        }

        if clause_type.is_empty() {
            // No by/without clause: sum(expr)
            Ok(format!("{}({})", agg_op, expr))
        } else {
            // With clause: sum by(labels) (expr)
            Ok(format!("{} {}({}) ({})", agg_op, clause_type, labels, expr))
        }
    }

    fn parse_binary_op_function_term(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut op_name = String::new();
        let mut left_expr = String::new();
        let mut right_expr = String::new();
        let mut modifiers = Vec::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::binary_op_name => {
                    op_name = inner.as_str().to_string();
                }
                Rule::binary_op_template => {
                    modifiers = self.parse_binary_op_template(inner)?;
                }
                Rule::expression => {
                    if left_expr.is_empty() {
                        left_expr = self.parse_expression(inner)?;
                    } else {
                        right_expr = self.parse_expression(inner)?;
                    }
                }
                _ => {}
            }
        }

        let op_symbol = match op_name.as_str() {
            "add" => "+",
            "sub" => "-",
            "mul" => "*",
            "div" => "/",
            "mod" => "%",
            "pow" => "^",
            _ => return Err(format!("Unknown binary operation: {}", op_name)),
        };

        if modifiers.is_empty() {
            Ok(format!("{} {} {}", left_expr, op_symbol, right_expr))
        } else {
            Ok(format!("{} {} {} {}", left_expr, op_symbol, modifiers.join(" "), right_expr))
        }
    }

    fn parse_binary_op_function(&mut self, pair: pest::iterators::Pair<Rule>, current_expr: &str) -> Result<String, String> {
        let mut op_name = String::new();
        let mut right_expr = String::new();
        let mut modifiers = Vec::new();
        let mut postfix_sel = None;

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::binary_op_name => {
                    op_name = inner.as_str().to_string();
                }
                Rule::binary_op_template => {
                    modifiers = self.parse_binary_op_template(inner)?;
                }
                Rule::expression => {
                    right_expr = self.parse_expression(inner)?;
                }
                Rule::postfix_selector => {
                    postfix_sel = Some(self.parse_postfix_selector(inner)?);
                }
                _ => {}
            }
        }

        let op_symbol = match op_name.as_str() {
            "add" => "+",
            "sub" => "-",
            "mul" => "*",
            "div" => "/",
            "mod" => "%",
            "pow" => "^",
            _ => return Err(format!("Unknown binary operation: {}", op_name)),
        };

        let result = if modifiers.is_empty() {
            format!("{} {} {}", current_expr, op_symbol, right_expr)
        } else {
            format!("{} {} {} {}", current_expr, op_symbol, modifiers.join(" "), right_expr)
        };

        // Apply postfix selector if present
        if let Some(sel) = postfix_sel {
            let needs_parens = result.contains(' ') || result.contains('(');
            if needs_parens {
                Ok(format!("({}){}", result, sel))
            } else {
                Ok(format!("{}{}", result, sel))
            }
        } else {
            Ok(result)
        }
    }

    fn parse_binary_op_template(&self, pair: pest::iterators::Pair<Rule>) -> Result<Vec<String>, String> {
        let mut modifiers = Vec::new();

        for inner in pair.into_inner() {
            if inner.as_rule() == Rule::binary_op_modifier_item {
                modifiers.push(self.parse_binary_op_modifier_item(inner)?);
            }
        }

        Ok(modifiers)
    }

    fn parse_binary_op_modifier_item(&self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::on_modifier => {
                    let labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                    return Ok(format!("on({})", labels));
                }
                Rule::ignoring_modifier => {
                    let labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                    return Ok(format!("ignoring({})", labels));
                }
                Rule::group_left_modifier => {
                    let text = inner.as_str();
                    let has_parens = text.contains('(');
                    let mut labels = Vec::new();
                    for label_list in inner.into_inner() {
                        if label_list.as_rule() == Rule::label_list {
                            labels = label_list
                                .into_inner()
                                .map(|p| p.as_str())
                                .collect::<Vec<_>>();
                        }
                    }
                    if !has_parens {
                        return Ok("group_left".to_string());
                    } else if labels.is_empty() {
                        return Ok("group_left()".to_string());
                    } else {
                        return Ok(format!("group_left({})", labels.join(", ")));
                    }
                }
                Rule::group_right_modifier => {
                    let text = inner.as_str();
                    let has_parens = text.contains('(');
                    let mut labels = Vec::new();
                    for label_list in inner.into_inner() {
                        if label_list.as_rule() == Rule::label_list {
                            labels = label_list
                                .into_inner()
                                .map(|p| p.as_str())
                                .collect::<Vec<_>>();
                        }
                    }
                    if !has_parens {
                        return Ok("group_right".to_string());
                    } else if labels.is_empty() {
                        return Ok("group_right()".to_string());
                    } else {
                        return Ok(format!("group_right({})", labels.join(", ")));
                    }
                }
                _ => {}
            }
        }
        Err("Invalid binary op modifier".to_string())
    }

    fn parse_alias(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<(), String> {
        let mut name = String::new();
        let mut raw_expr = String::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::identifier => {
                    name = inner.as_str().to_string();
                }
                Rule::expression => {
                    // Store the raw text of the expression, not the evaluated result
                    raw_expr = inner.as_str().to_string();
                }
                _ => {}
            }
        }

        self.aliases.insert(name, raw_expr);
        Ok(())
    }

    // Evaluate a raw expression string with optional placeholder substitution
    fn eval_expr(&mut self, expr: &str, placeholder: Option<&str>) -> Result<String, String> {
        // Parse the expression
        let pairs = PromQLParser::parse(Rule::expression, expr)
            .map_err(|e| format!("Parse error in expression '{}': {}", expr, e))?;

        // Temporarily set placeholder value if provided
        let old_placeholder = if let Some(p) = placeholder {
            self.aliases.insert("".to_string(), p.to_string())
        } else {
            None
        };

        let result = pairs
            .into_iter()
            .next()
            .map(|p| self.parse_expression(p))
            .ok_or_else(|| "Empty expression".to_string())??;

        // Restore old placeholder state
        if placeholder.is_some() {
            if let Some(old) = old_placeholder {
                self.aliases.insert("".to_string(), old);
            } else {
                self.aliases.remove("");
            }
        }

        Ok(result)
    }

    fn parse_pipeline(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut current_expr = String::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::term => {
                    current_expr = self.parse_term(inner)?;
                }
                Rule::stage => {
                    current_expr = self.parse_stage(inner, &current_expr)?;
                }
                _ => {}
            }
        }

        Ok(current_expr)
    }

    fn parse_term(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut base_expr = String::new();
        let mut postfix_selectors = Vec::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::expression => {
                    // Parenthesized expression - supports pipelines!
                    let expr = self.parse_expression(inner)?;
                    base_expr = format!("({})", expr);
                }
                Rule::binary_op_function_term => {
                    base_expr = self.parse_binary_op_function_term(inner)?;
                }
                Rule::aggregation_term => {
                    base_expr = self.parse_aggregation_term(inner)?;
                }
                Rule::sugar_function_term => {
                    base_expr = self.parse_sugar_function_term(inner)?;
                }
                Rule::function_call_term => {
                    base_expr = self.parse_function_call_term(inner)?;
                }
                Rule::reference => {
                    if let Some(identifier) = inner.into_inner().next() {
                        let ref_name = identifier.as_str();
                        let raw_expr = self.aliases
                            .get(ref_name)
                            .cloned()
                            .ok_or_else(|| format!("Unknown reference: ${}", ref_name))?;
                        // Evaluate the raw expression (no placeholder substitution at this level)
                        base_expr = self.eval_expr(&raw_expr, None)?;
                    } else {
                        // $ placeholder - check if we have a placeholder value stored
                        if let Some(placeholder_val) = self.aliases.get("") {
                            base_expr = placeholder_val.clone();
                        } else {
                            // No placeholder value - error
                            return Err("$ placeholder used outside of pipeline context".to_string());
                        }
                    }
                }
                Rule::metric_with_labels => {
                    base_expr = self.parse_metric_with_labels(inner)?;
                }
                Rule::metric_selector => {
                    base_expr = self.parse_metric_selector(inner)?;
                }
                Rule::number => {
                    base_expr = inner.as_str().to_string();
                }
                Rule::identifier => {
                    let id = inner.as_str();
                    // Check if this identifier is an alias
                    if let Some(alias_value) = self.aliases.get(id) {
                        base_expr = alias_value.clone();
                    } else {
                        base_expr = id.to_string();
                    }
                }
                Rule::postfix_selector => {
                    postfix_selectors.push(self.parse_postfix_selector(inner)?);
                }
                _ => {}
            }
        }

        // Apply postfix selectors
        let mut result = base_expr;
        for selector in postfix_selectors {
            result = format!("{}{}", result, selector);
        }

        Ok(result)
    }

    fn parse_function_call_term(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut func_name = String::new();
        let mut args = Vec::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::identifier => {
                    func_name = inner.as_str().to_string();
                }
                Rule::function_args => {
                    for arg in inner.into_inner() {
                        if arg.as_rule() == Rule::function_arg {
                            // For function_call_term, there's no "current_expr" context
                            args.push(self.parse_function_arg(arg, "")?);
                        }
                    }
                }
                _ => {}
            }
        }

        Ok(format!("{}({})", func_name, args.join(", ")))
    }

    fn parse_sugar_function_term(&mut self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut func_name = String::new();
        let mut args = Vec::new();
        let mut agg_clause = None;

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::sugar_func_name => {
                    func_name = inner.as_str().to_string();
                }
                Rule::aggregation_template => {
                    agg_clause = Some(self.parse_aggregation_template(inner)?);
                }
                Rule::sugar_args => {
                    for arg in inner.into_inner() {
                        match arg.as_rule() {
                            Rule::dollar_placeholder => {
                                // In term context, $ has no meaning, skip it or error?
                                return Err("$ placeholder cannot be used in non-pipeline context".to_string());
                            }
                            Rule::reference => {
                                // Resolve reference like $alias or $ placeholder
                                if let Some(identifier) = arg.into_inner().next() {
                                    let ref_name = identifier.as_str();
                                    let raw_expr = self.aliases
                                        .get(ref_name)
                                        .cloned()
                                        .ok_or_else(|| format!("Unknown reference: ${}", ref_name))?;
                                    let resolved = self.eval_expr(&raw_expr, None)?;
                                    args.push(resolved);
                                } else if let Some(placeholder_val) = self.aliases.get("") {
                                    args.push(placeholder_val.clone());
                                } else {
                                    return Err("$ placeholder used outside of pipeline context".to_string());
                                }
                            }
                            Rule::sugar_arg => {
                                // Plain argument
                                args.push(arg.as_str().trim().to_string());
                            }
                            Rule::sugar_arg_complex => {
                                // This handles things like $alias[5m]
                                return Err("Complex arguments not yet supported in term context".to_string());
                            }
                            _ => {}
                        }
                    }
                }
                _ => {}
            }
        }

        // Handle aggregation template functions like #bottomk<without(instance)>(expr, 10)
        if let Some((clause_type, labels)) = agg_clause {
            return Ok(format!("{} {}({}) ({})", func_name, clause_type, labels, args.join(", ")));
        }

        // If no arguments provided, check if we have a placeholder value to use
        if args.is_empty() {
            if let Some(placeholder_val) = self.aliases.get("") {
                args.push(placeholder_val.clone());
            }
        }

        // For other sugar functions in term context, just call them as regular functions
        Ok(format!("{}({})", func_name, args.join(", ")))
    }

    fn parse_postfix_selector(&self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let inner_text = pair.as_str();

        // Check if it's a subquery with empty resolution: [5m:]
        if inner_text.ends_with(":]") {
            return Ok(inner_text.to_string());
        }

        let parts: Vec<_> = pair.into_inner().map(|p| p.as_str()).collect();

        if parts.len() == 2 {
            // Subquery: [5m:1m]
            Ok(format!("[{}:{}]", parts[0], parts[1]))
        } else if parts.len() == 1 {
            // Range: [5m] or could be part of [5m:] but that's handled above
            Ok(format!("[{}]", parts[0]))
        } else {
            Err("Invalid postfix selector".to_string())
        }
    }



    fn parse_metric_with_labels(
        &self,
        pair: pest::iterators::Pair<Rule>,
    ) -> Result<String, String> {
        let mut metric_name = String::new();
        let mut selector = String::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::identifier => {
                    metric_name = inner.as_str().to_string();
                }
                Rule::metric_selector => {
                    selector = self.parse_metric_selector(inner)?;
                }
                _ => {}
            }
        }

        Ok(format!("{}{}", metric_name, selector))
    }

    fn parse_metric_selector(&self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut selectors = Vec::new();

        for inner in pair.into_inner() {
            if inner.as_rule() == Rule::label_selector {
                selectors.push(self.parse_label_selector(inner)?);
            }
        }

        Ok(format!("{{{}}}", selectors.join(", ")))
    }

    fn parse_label_selector(&self, pair: pest::iterators::Pair<Rule>) -> Result<String, String> {
        let mut parts = Vec::new();

        for inner in pair.into_inner() {
            parts.push(inner.as_str().to_string());
        }

        Ok(parts.join(""))
    }

    fn parse_stage(
        &mut self,
        pair: pest::iterators::Pair<Rule>,
        current_expr: &str,
    ) -> Result<String, String> {
        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::range_selector => {
                    let duration = inner.into_inner().next().unwrap().as_str();
                    return Ok(format!("{}[{}]", current_expr, duration));
                }
                Rule::subquery_selector => {
                    let mut durations = inner.into_inner();
                    let range = durations.next().unwrap().as_str();
                    let resolution = durations.next();

                    let needs_parens = current_expr.contains(' ') || current_expr.contains('(');

                    match resolution {
                        Some(res) => {
                            // $[5m:1m] - with resolution
                            if needs_parens {
                                return Ok(format!("({})[{}:{}]", current_expr, range, res.as_str()));
                            }
                            return Ok(format!("{}[{}:{}]", current_expr, range, res.as_str()));
                        }
                        None => {
                            // $[5m:] - empty resolution (uses default from range)
                            if needs_parens {
                                return Ok(format!("({})[{}:]", current_expr, range));
                            }
                            return Ok(format!("{}[{}:]", current_expr, range));
                        }
                    }
                }
                Rule::offset_modifier => {
                    let duration = inner.into_inner().next().unwrap().as_str();
                    return Ok(format!("{} offset {}", current_expr, duration));
                }
                Rule::at_modifier => {
                    let value = inner.into_inner().next().unwrap();
                    let at_value = match value.as_rule() {
                        Rule::at_function => value.as_str().to_string(),
                        Rule::timestamp => value.as_str().to_string(),
                        _ => value.as_str().to_string(),
                    };
                    return Ok(format!("{} @ {}", current_expr, at_value));
                }
                Rule::sugar_function => {
                    return self.parse_sugar_function(inner, current_expr);
                }
                Rule::binary_op_function => {
                    return self.parse_binary_op_function(inner, current_expr);
                }
                Rule::aggregation => {
                    return self.parse_aggregation(inner, current_expr);
                }
                Rule::function_call => {
                    return self.parse_function_call(inner, current_expr);
                }
                Rule::reference => {
                    // Reference to an alias that may contain a pipeline template
                    if let Some(identifier) = inner.into_inner().next() {
                        let ref_name = identifier.as_str();
                        let raw_expr = self.aliases
                            .get(ref_name)
                            .cloned()
                            .ok_or_else(|| format!("Unknown reference: ${}", ref_name))?;

                        // Evaluate the alias with current_expr as the placeholder value
                        return self.eval_expr(&raw_expr, Some(current_expr));
                    } else {
                        // Bare $ placeholder - return current expr
                        return Ok(current_expr.to_string());
                    }
                }
                _ => {}
            }
        }
        Ok(current_expr.to_string())
    }

    fn parse_sugar_function(
        &mut self,
        pair: pest::iterators::Pair<Rule>,
        current_expr: &str,
    ) -> Result<String, String> {
        let mut func_name = String::new();
        let mut args = Vec::new();
        let mut agg_clause = None;
        let mut postfix_sel = None;

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::sugar_func_name => {
                    func_name = inner.as_str().to_string();
                }
                Rule::aggregation_template => {
                    agg_clause = Some(self.parse_aggregation_template(inner)?);
                }
                Rule::sugar_args => {
                    for arg in inner.into_inner() {
                        match arg.as_rule() {
                            Rule::dollar_placeholder => {
                                // Explicit $ - we use current_expr anyway, don't add to args
                            }
                            Rule::reference => {
                                // Resolve reference like $alias or $ placeholder
                                if let Some(identifier) = arg.into_inner().next() {
                                    let ref_name = identifier.as_str();
                                    let raw_expr = self.aliases
                                        .get(ref_name)
                                        .cloned()
                                        .ok_or_else(|| format!("Unknown reference: ${}", ref_name))?;
                                    let resolved = self.eval_expr(&raw_expr, None)?;
                                    args.push(resolved);
                                } else {
                                    // Bare $ placeholder - don't add to args, current_expr is used separately
                                }
                            }
                            Rule::sugar_arg => {
                                args.push(arg.as_str().to_string());
                            }
                            _ => {}
                        }
                    }
                }
                Rule::postfix_selector => {
                    postfix_sel = Some(self.parse_postfix_selector(inner)?);
                }
                _ => {}
            }
        }

        // If there's an aggregation clause, treat as function call with that clause
        if let Some((clause_type, labels)) = agg_clause {
            // #bottomk<without(instance)>($, 10) -> bottomk without(instance) (arg1, arg2, ...)
            // Need to expand args with current_expr if $ is used
            let expanded_args: Vec<String> = args.iter().map(|arg| {
                if arg.trim() == "$" {
                    current_expr.to_string()
                } else {
                    arg.to_string()
                }
            }).collect();

            // If args is empty, add current_expr as implicit first argument
            let final_args = if expanded_args.is_empty() {
                vec![current_expr.to_string()]
            } else {
                expanded_args
            };

            let result = format!("{} {}({}) ({})", func_name, clause_type, labels, final_args.join(", "));

            // Apply postfix selector if present
            if let Some(sel) = postfix_sel {
                return Ok(format!("({}){}", result, sel));
            }
            return Ok(result);
        }

        // Helper to apply postfix selector
        let apply_postfix = |base: String| -> String {
            if let Some(sel) = &postfix_sel {
                let needs_parens = base.contains(' ') || base.contains('(');
                if needs_parens {
                    format!("({}){}", base, sel)
                } else {
                    format!("{}{}", base, sel)
                }
            } else {
                base
            }
        };

        // Convert sugar syntax to appropriate PromQL syntax
        match func_name.as_str() {
            "offset" => {
                if args.len() == 1 {
                    Ok(apply_postfix(format!("{} offset {}", current_expr, args[0])))
                } else {
                    Err("!offset requires 1 argument: duration".to_string())
                }
            }
            "at" => {
                if args.len() == 1 {
                    Ok(apply_postfix(format!("{} @ {}", current_expr, args[0])))
                } else {
                    Err("!at requires 1 argument: timestamp".to_string())
                }
            }
            "at_start" => {
                if args.is_empty() {
                    Ok(apply_postfix(format!("{} @ start()", current_expr)))
                } else {
                    Err("#at_start takes no arguments".to_string())
                }
            }
            "at_end" => {
                if args.is_empty() {
                    Ok(apply_postfix(format!("{} @ end()", current_expr)))
                } else {
                    Err("#at_end takes no arguments".to_string())
                }
            }
            "resample" => {
                // Note: #resample already applies a postfix selector, so we should warn if another is provided
                if postfix_sel.is_some() {
                    return Err("#resample already applies a subquery selector; cannot add another".to_string());
                }
                if args.len() == 1 {
                    // #resample($, 5m) -> $[5m:5m] (resolution defaults to range)
                    let needs_parens = current_expr.contains(' ') || current_expr.contains('(');
                    if needs_parens {
                        Ok(format!("({})[{}:{}]", current_expr, args[0], args[0]))
                    } else {
                        Ok(format!("{}[{}:{}]", current_expr, args[0], args[0]))
                    }
                } else if args.len() == 2 {
                    // #resample($, 5m, 1m) -> $[5m:1m]
                    let needs_parens = current_expr.contains(' ') || current_expr.contains('(');
                    if needs_parens {
                        Ok(format!("({})[{}:{}]", current_expr, args[0], args[1]))
                    } else {
                        Ok(format!("{}[{}:{}]", current_expr, args[0], args[1]))
                    }
                } else {
                    Err("#resample requires 1 or 2 arguments: range [, resolution]".to_string())
                }
            }
            "rate" => {
                if args.is_empty() {
                    // #rate -> rate($) or #rate[5m:] -> rate($)[5m:]
                    Ok(apply_postfix(format!("rate({})", current_expr)))
                } else {
                    Err("#rate takes no arguments (operates on $)".to_string())
                }
            }
            _ => Err(format!("Unknown sugar function: {}. Available: offset, at, at_start, at_end, resample, rate", func_name)),
        }
    }

    fn parse_aggregation(
        &self,
        pair: pest::iterators::Pair<Rule>,
        current_expr: &str,
    ) -> Result<String, String> {
        let mut func_name = String::new();
        let mut labels = String::new();
        let mut clause_type = String::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::identifier => {
                    func_name = inner.as_str().to_string();
                }
                Rule::by_clause => {
                    clause_type = "by".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                Rule::without_clause => {
                    clause_type = "without".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                _ => {}
            }
        }

        Ok(format!(
            "{} {}({}) ({})",
            func_name, clause_type, labels, current_expr
        ))
    }

    fn parse_aggregation_template(&self, pair: pest::iterators::Pair<Rule>) -> Result<(String, String), String> {
        let mut clause_type = String::new();
        let mut labels = String::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::by_clause => {
                    clause_type = "by".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                Rule::without_clause => {
                    clause_type = "without".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                Rule::wo_clause => {
                    clause_type = "without".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                _ => {}
            }
        }

        Ok((clause_type, labels))
    }

    fn parse_function_call(
        &mut self,
        pair: pest::iterators::Pair<Rule>,
        current_expr: &str,
    ) -> Result<String, String> {
        let mut func_name = String::new();
        let mut args = Vec::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::identifier => {
                    func_name = inner.as_str().to_string();
                }
                Rule::function_args => {
                    for arg in inner.into_inner() {
                        if arg.as_rule() == Rule::function_arg {
                            args.push(self.parse_function_arg(arg, current_expr)?);
                        }
                    }
                }
                _ => {}
            }
        }

        Ok(format!("{}({})", func_name, args.join(", ")))
    }

    fn parse_function_arg(&mut self, pair: pest::iterators::Pair<Rule>, current_expr: &str) -> Result<String, String> {
        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::term_in_function => {
                    return self.parse_term_in_function(inner, current_expr);
                }
                Rule::dollar_placeholder => {
                    return Ok(current_expr.to_string());
                }
                Rule::plain_arg => {
                    return Ok(inner.as_str().trim().to_string());
                }
                _ => {}
            }
        }
        Ok(String::new())
    }

    fn parse_term_in_function(&mut self, pair: pest::iterators::Pair<Rule>, current_expr: &str) -> Result<String, String> {
        let mut base_expr = String::new();
        let mut postfix_selectors = Vec::new();

        // Check if this is an aggregation
        let mut agg_op = String::new();
        let mut clause_type = String::new();
        let mut labels = String::new();
        let mut expr = String::new();

        for inner in pair.into_inner() {
            match inner.as_rule() {
                Rule::aggregation_op => {
                    agg_op = inner.as_str().to_string();
                }
                Rule::by_clause => {
                    clause_type = "by".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                Rule::without_clause => {
                    clause_type = "without".to_string();
                    labels = inner
                        .into_inner()
                        .next()
                        .unwrap()
                        .into_inner()
                        .map(|p| p.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                }
                Rule::expression => {
                    // This could be inside parentheses or inside aggregation
                    if agg_op.is_empty() {
                        // It's a parenthesized expression
                        base_expr = format!("({})", self.parse_expression(inner)?);
                    } else {
                        // It's the expression inside an aggregation
                        expr = self.parse_expression(inner)?;
                    }
                }
                Rule::reference => {
                    if let Some(identifier) = inner.into_inner().next() {
                        let ref_name = identifier.as_str();
                        let raw_expr = self.aliases
                            .get(ref_name)
                            .cloned()
                            .ok_or_else(|| format!("Unknown reference: ${}", ref_name))?;
                        // Evaluate the raw expression (no placeholder substitution at this level)
                        base_expr = self.eval_expr(&raw_expr, None)?;
                    } else {
                        // $ placeholder - use current_expr from pipeline context
                        base_expr = current_expr.to_string();
                    }
                }
                Rule::metric_with_labels => {
                    base_expr = self.parse_metric_with_labels(inner)?;
                }
                Rule::metric_selector => {
                    base_expr = self.parse_metric_selector(inner)?;
                }
                Rule::number => {
                    base_expr = inner.as_str().to_string();
                }
                Rule::identifier => {
                    // Plain identifier (e.g., metric_name)
                    base_expr = inner.as_str().to_string();
                }
                Rule::postfix_selector => {
                    postfix_selectors.push(self.parse_postfix_selector(inner)?);
                }
                _ => {}
            }
        }

        // If we found an aggregation, return it
        if !agg_op.is_empty() {
            if clause_type.is_empty() {
                return Ok(format!("{}({})", agg_op, expr));
            } else {
                return Ok(format!("{} {}({}) ({})", agg_op, clause_type, labels, expr));
            }
        }

        // Apply postfix selectors
        let mut result = base_expr;
        for selector in postfix_selectors {
            result = format!("{}{}", result, selector);
        }

        Ok(result)
    }
}

pub fn pretty_print(promql: &str) -> String {
    let mut result = String::new();
    let mut indent_level: usize = 0;
    let mut chars = promql.chars().peekable();
    let mut last_was_newline = false;
    let mut in_braces: usize = 0; // Track if we're inside {...} metric selectors

    while let Some(ch) = chars.next() {
        match ch {
            '{' => {
                in_braces += 1;
                result.push(ch);
                last_was_newline = false;
            }
            '}' => {
                in_braces = in_braces.saturating_sub(1);
                result.push(ch);
                last_was_newline = false;
            }
            '(' => {
                result.push(ch);
                // Check if next char is not a closing paren
                if chars.peek() != Some(&')') {
                    indent_level += 1;
                    result.push('\n');
                    result.push_str(&"  ".repeat(indent_level));
                    last_was_newline = true;
                }
            }
            ')' => {
                if !last_was_newline {
                    indent_level = indent_level.saturating_sub(1);
                    result.push('\n');
                    result.push_str(&"  ".repeat(indent_level));
                } else {
                    indent_level = indent_level.saturating_sub(1);
                }
                result.push(ch);
                last_was_newline = false;
            }
            ',' if in_braces == 0 => {
                // Only add newlines for commas outside of {...}
                result.push(ch);
                result.push('\n');
                result.push_str(&"  ".repeat(indent_level));
                last_was_newline = true;
            }
            ' ' if last_was_newline => {
                // Skip spaces after newlines as we have our own indentation
                continue;
            }
            _ => {
                result.push(ch);
                last_was_newline = false;
            }
        }
    }

    result
}
