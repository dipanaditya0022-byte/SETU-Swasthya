from faker import Faker
import random
import uuid
import pandas as pd


fake = Faker()

records = []


for i in range(1000):

    # -------------------------
    # Basic patient information
    # -------------------------

    age = random.randint(1, 80)

    village = fake.city()

    facility_id = str(uuid.uuid4())


    # -------------------------
    # Synthetic health values
    # -------------------------

    bp_systolic = random.randint(85, 190)

    bp_diastolic = random.randint(55, 125)

    hb = round(
        random.uniform(6.0, 17.5),
        1
    )


    # -------------------------
    # Synthetic risk scoring
    # -------------------------

    risk_score = 0


    # Age factor

    if age >= 60:
        risk_score += 2

    elif age >= 45:
        risk_score += 1


    # Blood pressure factor

    if bp_systolic >= 160:
        risk_score += 4

    elif bp_systolic >= 140:
        risk_score += 2

    elif bp_systolic >= 130:
        risk_score += 1


    if bp_diastolic >= 110:
        risk_score += 3

    elif bp_diastolic >= 90:
        risk_score += 2


    # Hemoglobin factor

    if hb < 7:
        risk_score += 4

    elif hb < 10:
        risk_score += 2


    # -------------------------
    # Convert score to label
    # -------------------------

    if risk_score >= 6:

        risk_label = "HIGH"

    elif risk_score >= 3:

        risk_label = "MEDIUM"

    else:

        risk_label = "LOW"


    # -------------------------
    # Create record
    # -------------------------

    record = {

        "patient_id": str(uuid.uuid4()),

        "name": fake.name(),

        "age": age,

        "village": village,

        "facility_id": facility_id,

        "bp_systolic": bp_systolic,

        "bp_diastolic": bp_diastolic,

        "hb": hb,

        "synthetic_risk_score": risk_score,

        "risk_label": risk_label

    }


    records.append(record)


# Convert to DataFrame

df = pd.DataFrame(records)


# Save dataset

output_path = "ml/data/synthetic_patients.csv"


df.to_csv(
    output_path,
    index=False
)


# Output

print("\n=================================")

print("SETU-SWASTHYA SYNTHETIC DATA READY")

print("=================================")

print("\nTotal records created:")

print(len(df))


print("\nRisk Distribution:")

print(
    df["risk_label"].value_counts()
)


print("\nDataset saved at:")

print(output_path)