"""Default configuration values."""

from code_audit.config.models import AgentConfig, AuditConfig, LLMConfig, LLMProvider

# ═══════════════════════════════════════════════════════════════
# PROVIDER CONFIGS (reusable building blocks)
# ═══════════════════════════════════════════════════════════════

_NVIDIA_KIMI = LLMConfig(
    provider=LLMProvider.NVIDIA,
    model="moonshotai/kimi-k2.5",
    api_key_env="NVIDIA_API_KEY",
)

_GEMINI_PAID = LLMConfig(
    provider=LLMProvider.GEMINI,
    model="gemini-2.5-flash",
    api_key_env="GEMINI_API_KEY_2",
)

_GEMINI_FREE = LLMConfig(
    provider=LLMProvider.GEMINI,
    model="gemini-2.5-flash",
    api_key_env="GEMINI_API_KEY",
)

# Ollama Cloud — hosted LLMs via api.ollama.com (OpenAI-compatible)
# Two keys for load distribution across two accounts
_OLLAMA_DEVSTRAL = LLMConfig(
    provider=LLMProvider.OPENAI_COMPAT,
    model="devstral",                        # 123B code-specialist
    api_key_env="OLLAMA_API_KEY",
    base_url="https://api.ollama.com/v1",
)

_OLLAMA_QWEN_CODER = LLMConfig(
    provider=LLMProvider.OPENAI_COMPAT,
    model="qwen3-coder",                     # Agentic coding model
    api_key_env="OLLAMA_API_KEY_2",
    base_url="https://api.ollama.com/v1",
)

_OPENROUTER_QWEN = LLMConfig(
    provider=LLMProvider.OPENAI_COMPAT,
    model="qwen/qwen3-next-80b-a3b-instruct:free",
    api_key_env="OPENROUTER_API_KEY_PAID",
    base_url="https://openrouter.ai/api/v1",
)

_OPENROUTER_GEMMA = LLMConfig(
    provider=LLMProvider.OPENAI_COMPAT,
    model="google/gemma-3-27b-it:free",
    api_key_env="OPENROUTER_API_KEY",
    base_url="https://openrouter.ai/api/v1",
)

# ═══════════════════════════════════════════════════════════════
# SPLIT ARCHITECTURE: Strong lead + fast workers
#
# Judge & Reflection: Kimi K2.5 (1T MoE, best reasoning)
#   → needs to deduplicate, cross-reference, and rank findings
#   → reasoning quality directly affects false positive rate
#   → receives ~2-5K tokens (findings only, not full code)
#
# Specialist Agents: Gemini paid + OpenRouter (distributed)
#   → process full codebase (~80-90K tokens each)
#   → max 2 agents run concurrently (see ReviewConfig.max_concurrency)
#   → prevents rate-limit cascade on free providers
#
# Fallback chain (6 deep, no paid Claude models):
#   Gemini paid → Kimi/Ollama → Gemini free → OpenRouter → Gemma
# ═══════════════════════════════════════════════════════════════

# Default LLM — security, architectural, performance agents (large context needed)
_DEFAULT_LLM = _GEMINI_PAID.model_copy(update={
    "fallbacks": [
        _NVIDIA_KIMI,
        _OLLAMA_DEVSTRAL,
        _GEMINI_FREE,
        _OPENROUTER_QWEN,
        _OPENROUTER_GEMMA,
    ],
})

# Judge LLM — strongest reasoning model first; only sees findings (~2-5K tokens)
_JUDGE_LLM = _NVIDIA_KIMI.model_copy(update={
    "fallbacks": [
        _GEMINI_PAID,
        _OLLAMA_QWEN_CODER,
        _GEMINI_FREE,
        _OPENROUTER_QWEN,
        _OPENROUTER_GEMMA,
    ],
})

# OpenRouter agent LLM — functional, maintainability agents
_OPENROUTER_AGENT_LLM = _OPENROUTER_QWEN.model_copy(update={
    "fallbacks": [
        _GEMINI_PAID,
        _NVIDIA_KIMI,
        _OLLAMA_DEVSTRAL,
        _OPENROUTER_GEMMA,
        _GEMINI_FREE,
    ],
})

DEFAULT_CONFIG = AuditConfig(
    llm=_DEFAULT_LLM,
    agents={
        # Gemini paid handles 3 agents (uses default LLM)
        # security, architectural, performance → Gemini 2.5 Flash (paid)

        # OpenRouter handles 2 agents (distributed to avoid Gemini rate limits)
        "functional": AgentConfig(llm=_OPENROUTER_AGENT_LLM),
        "maintainability": AgentConfig(llm=_OPENROUTER_AGENT_LLM),

        # Judge: Kimi K2.5 — strongest reasoning, small input (findings only)
        "judge": AgentConfig(llm=_JUDGE_LLM),
    },
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
