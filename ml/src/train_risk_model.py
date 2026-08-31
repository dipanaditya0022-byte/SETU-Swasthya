import pandas as pd
import joblib

from sklearn.model_selection import train_test_split

from sklearn.pipeline import Pipeline

from sklearn.preprocessing import StandardScaler

from sklearn.linear_model import LogisticRegression

from sklearn.metrics import accuracy_score

from sklearn.metrics import classification_report

from sklearn.metrics import confusion_matrix


# ==============================
# LOAD DATASET
# ==============================

df = pd.read_csv(
    "ml/data/synthetic_patients.csv"
)


# ==============================
# SELECT FEATURES
# ==============================

features = [

    "age",

    "bp_systolic",

    "bp_diastolic",

    "hb"

]


X = df[features]


y = df["risk_label"]


# ==============================
# TRAIN / TEST SPLIT
# ==============================

X_train, X_test, y_train, y_test = train_test_split(

    X,

    y,

    test_size=0.20,

    random_state=42,

    stratify=y

)


# ==============================
# CREATE MODEL PIPELINE
# ==============================

model = Pipeline([

    (

        "scaler",

        StandardScaler()

    ),

    (

        "classifier",

        LogisticRegression(

            max_iter=2000

        )

    )

])


# ==============================
# TRAIN MODEL
# ==============================

print("\nTraining SETU-Swasthya Risk Model...\n")


model.fit(

    X_train,

    y_train

)


# ==============================
# MAKE PREDICTIONS
# ==============================

predictions = model.predict(

    X_test

)


# ==============================
# EVALUATE MODEL
# ==============================

accuracy = accuracy_score(

    y_test,

    predictions

)


print("=================================")

print("MODEL ACCURACY")

print("=================================")

print(accuracy)


print("\n=================================")

print("CLASSIFICATION REPORT")

print("=================================")

print(

    classification_report(

        y_test,

        predictions

    )

)


print("\n=================================")

print("CONFUSION MATRIX")

print("=================================")

print(

    confusion_matrix(

        y_test,

        predictions

    )

)


# ==============================
# SAVE MODEL
# ==============================

model_path = "ml/models/risk_model.joblib"


joblib.dump(

    model,

    model_path

)


print("\n=================================")

print("MODEL SAVED SUCCESSFULLY!")

print("Location:", model_path)

print("=================================")