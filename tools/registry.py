"""Tool registry: TOOLS dictionary, @tool decorator, and schema generation."""

import inspect

TOOLS: dict = {}

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}


def tool(
    name: str,
    readonly: bool,
    description: str,
    params: dict | None = None,
    requires: tuple = (),
):
    """Register a tool. Parameter types are derived from function annotations."""

    def decorator(func):
        if name in TOOLS:
            raise ValueError(f"Tool '{name}' is already registered")

        tool_description = description

        if requires:
            required_commands = ", ".join(requires)
            tool_description = (
                f"{description} "
                f"This tool requires the following host command(s) to be "
                f"available: {required_commands}."
                f"If this tool executes successfully, these required command(s) "
                f"are available on the host system."
            )

        TOOLS[name] = {
            "func": func,
            "readonly": readonly,
            "description": tool_description,
            "schema": _build_schema(func, params or {}),
            "requires": tuple(requires),
        }

        return func

    return decorator


def _build_schema(func, param_descriptions: dict) -> dict:
    """Build the JSON schema from the function signature."""

    sig = inspect.signature(func)
    properties, required = {}, []

    for pname, param in sig.parameters.items():
        prop = {"type": _TYPE_MAP.get(param.annotation, "string")}

        if pname in param_descriptions:
            prop["description"] = param_descriptions[pname]

        properties[pname] = prop

        if param.default is inspect.Parameter.empty:
            required.append(pname)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def is_available(entry: dict) -> bool:
    """Check whether the tool's required host commands are available."""

    from appenv import which_host

    return all(which_host(command) for command in entry.get("requires", ()))


