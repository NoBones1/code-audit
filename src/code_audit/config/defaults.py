"""Default configuration values."""

from code_audit.config.models import AuditConfig, LLMConfig, LLMProvider

# Default provider chain: Gemini Paid → NVIDIA → Venice → Gemini Free → OpenRouter
#
# Priority logic:
#   1. Gemini 2.5 Flash (paid) — cheapest at ~$0.08/review, high rate limits, reliable
#   2. NVIDIA Kimi K2.5 — free but disconnects on large contexts (>50K tokens)
#   3. Venice Sonnet — Claude-quality but $1.78/day DIEM budget (~1 deep review/day)
#   4. Gemini 2.5 Flash (free) — 1,400 RPD limit, good for ~4-5 reviews/day
#   5. OpenRouter Qwen3 — free model, paid key (1,000 RPD)
#   6. OpenRouter Gemma 3 — free model, free key (50 RPD)
DEFAULT_CONFIG = AuditConfig(
    llm=LLMConfig(
        provider=LLMProvider.GEMINI,
        model="gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY_2",
        fallbacks=[
            LLMConfig(
                provider=LLMProvider.NVIDIA,
                model="moonshotai/kimi-k2.5",
                api_key_env="NVIDIA_API_KEY",
            ),
            LLMConfig(
                provider=LLMProvider.OPENAI_COMPAT,
                model="claude-sonnet-4-6",
                api_key_env="VENICE_API_KEY",
                base_url="https://api.venice.ai/api/v1",
            ),
            LLMConfig(
                provider=LLMProvider.GEMINI,
                model="gemini-2.5-flash",
                api_key_env="GEMINI_API_KEY",
            ),
            LLMConfig(
                provider=LLMProvider.OPENAI_COMPAT,
                model="qwen/qwen3-next-80b-a3b-instruct:free",
                api_key_env="OPENROUTER_API_KEY_PAID",
                base_url="https://openrouter.ai/api/v1",
            ),
            LLMConfig(
                provider=LLMProvider.OPENAI_COMPAT,
                model="google/gemma-3-27b-it:free",
                api_key_env="OPENROUTER_API_KEY",
                base_url="https://openrouter.ai/api/v1",
            ),
        ],
    ),
)

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
