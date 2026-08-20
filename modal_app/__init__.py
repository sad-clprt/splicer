"""Modal app package — ensures all functions are registered when deployed as package.

Deploy with:
    modal deploy -m modal_app.app
or run locally:
    modal run -m modal_app.proxy --film-id i_am_legend_ed264664
"""

# Import app and all endpoint modules so functions register to App
from . import app  # noqa: F401
from . import proxy  # noqa: F401
# Future: from . import audio, visual, tts, safety  # noqa: F401
