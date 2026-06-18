import pandas as pd
import os

def save_to_csv(data, filepath):
    os.makedirs("output", exist_ok=True)

    df = pd.DataFrame(data)

    df.to_csv(filepath, index=False)

    print("Saved:", filepath)