from fitparse import FitFile

fit_path = "data/fit/21201819948/21201819948_ACTIVITY.fit"

fitfile = FitFile(fit_path)

for msg in fitfile.get_messages():
    print(msg.name)
    for field in msg:
        print(f"  {field.name}: {field.value}")
