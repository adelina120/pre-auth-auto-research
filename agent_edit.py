def create_browser_use_prompt(BASE_URL, patient_name):
    return f""" Visit the web app at {BASE_URL}. On the first log-in page, do user sign-in with username "user2" and password "pass789". 
    Then find the patient record for {patient_name} using the patient search function on the site, then fill out and submit a Pre-Authorization Form for this patient. 
    Verify all required fields and then directly submit. If you find any issues, immediately stop the process and report the issue."""

LLM = "gemini-flash-latest"
max_steps = 30
