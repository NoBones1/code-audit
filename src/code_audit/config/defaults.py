"""Default configuration values."""

from code_audit.config.models import AuditConfig

DEFAULT_CONFIG = AuditConfig()

# File extensions → language mapping
EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (TSX)",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".scala": "Scala",
    ".ex": "Elixir",
    ".exs": "Elixir Script",
    ".erl": "Erlang",
    ".hs": "Haskell",
    ".lua": "Lua",
    ".r": "R",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Bash",
    ".zsh": "Zsh",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".xml": "XML",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "LESS",
    ".md": "Markdown",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".dart": "Dart",
    ".zig": "Zig",
}

# Framework detection: manifest file → framework name
FRAMEWORK_DETECTION: dict[str, list[tuple[str, str]]] = {
    # filename → list of (search_string, framework_name)
    "package.json": [
        ("react", "React"),
        ("next", "Next.js"),
        ("vue", "Vue.js"),
        ("nuxt", "Nuxt.js"),
        ("angular", "Angular"),
        ("svelte", "Svelte"),
        ("express", "Express.js"),
        ("fastify", "Fastify"),
        ("nest", "NestJS"),
        ("hono", "Hono"),
        ("remix", "Remix"),
        ("astro", "Astro"),
    ],
    "pyproject.toml": [
        ("django", "Django"),
        ("flask", "Flask"),
        ("fastapi", "FastAPI"),
        ("starlette", "Starlette"),
        ("pydantic", "Pydantic"),
        ("sqlalchemy", "SQLAlchemy"),
        ("pytest", "pytest"),
    ],
    "Cargo.toml": [
        ("actix", "Actix"),
        ("axum", "Axum"),
        ("tokio", "Tokio"),
        ("warp", "Warp"),
    ],
    "go.mod": [
        ("gin-gonic", "Gin"),
        ("gorilla/mux", "Gorilla Mux"),
        ("fiber", "Fiber"),
    ],
    "Gemfile": [
        ("rails", "Ruby on Rails"),
        ("sinatra", "Sinatra"),
    ],
}

# Config file names to search for (priority order)
CONFIG_FILE_NAMES = [
    "audit.config.yaml",
    "audit.config.yml",
    "audit.config.json",
    ".code-audit.yaml",
    ".code-audit.yml",
]

GLOBAL_CONFIG_DIR = "~/.config/code-audit"
GLOBAL_CONFIG_FILE = "config.yaml"
