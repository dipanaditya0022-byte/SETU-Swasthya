import pandas as pd


df = pd.read_csv(
    "ml/data/synthetic_patients.csv"
)


print("\n========== FIRST 5 RECORDS ==========")

print(
    df.head()
)


print("\n========== DATASET SHAPE ==========")

print(
    df.shape
)


print("\n========== COLUMNS ==========")

print(
    df.columns.tolist()
)


print("\n========== MISSING VALUES ==========")

print(
    df.isnull().sum()
)


print("\n========== RISK DISTRIBUTION ==========")

print(
    df["risk_label"].value_counts()
)


print("\n========== NUMERICAL SUMMARY ==========")

print(
    df[
        [
            "age",
            "bp_systolic",
            "bp_diastolic",
            "hb",
            "synthetic_risk_score"
        ]
    ].describe()
)