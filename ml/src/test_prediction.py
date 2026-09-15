import joblib
import pandas as pd


# Load trained model

model = joblib.load(

    "ml/models/risk_model.joblib"

)


# Demo patient

patient = pd.DataFrame([

    {

        "age": 62,

        "bp_systolic": 165,

        "bp_diastolic": 105,

        "hb": 8.2

    }

])


# Prediction

prediction = model.predict(

    patient

)[0]


# Probability

probabilities = model.predict_proba(

    patient

)[0]


classes = model.classes_


print("\n=================================")

print("SETU-SWASTHYA RISK PREDICTION")

print("=================================")


print("\nPatient Data:")

print(patient)


print("\nPredicted Risk:")

print(prediction)


print("\nRisk Probabilities:")


for label, probability in zip(

    classes,

    probabilities

):

    print(

        f"{label}: {probability:.2%}"

    )