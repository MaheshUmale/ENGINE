import sys
try:
    import pandas as pd
    import numpy as np
    import sqlalchemy
    import plotly
    import scipy
    import duckdb
    print("Core dependencies OK")
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)
