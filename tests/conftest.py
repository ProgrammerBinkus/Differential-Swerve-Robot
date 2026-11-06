import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """One hidden Tk window for the whole test run: creating several in a row is unreliable on Windows."""
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    window.withdraw()
    yield window
    window.destroy()
