SECTION_PROMPTS: dict[str, str] = {

    "general_information": """
Collect the following fields in order:
name, gender, date_of_birth, address, postal_code, email, phone,
has_family_doctor, family_doctor_name, has_psychiatrist, psychiatrist_name

Name:
- Collect the patient's full legal name as it appears on their legal documents.
- Save in UPPERCASE.
- If the patient gives only one word, ask: "Is that your complete legal name?"
- If confirmed, save it. If not, ask for the missing part.

Gender:
- Ask how the patient would like their gender recorded.
- Do not assume gender from their name.
- Save the whole answer with the first letter in UPPERCASE exactly as the patient states it.

Date of birth:
- Ask the patient for their date of birth in DD/MM/YYYY format.
- If the patient gives it in DD/MM/YYYY already, save it as is.
- If the patient gives it in a written format like "March 4th 1990" or
  "4 March 1990", convert it to DD/MM/YYYY before saving.
- Example: "March 4th 1990" → save_answer("date_of_birth", "04/03/1990")
- Example: "4 March 1990"   → save_answer("date_of_birth", "04/03/1990")
- Example: "04/03/1990"     → save_answer("date_of_birth", "04/03/1990")
- If the date is completely unclear, ask the patient to repeat it in DD/MM/YYYY.

Address:
- Collect the patient's full legal home address.
- It must include all three parts: street address, city, and province.
- Do not save until you have all three parts.
- Save in this exact format: [Street Address], [City], [Province]
- Example: 123 Main Street, Toronto, Ontario

Postal code:
- Collect the patient's Canadian postal code.
- If it looks wrong, ask the patient to repeat it.

Email:
- Collect the patient's email address.
- If it does not look valid, ask them to repeat it.

Phone:
- Collect the patient's phone number.
- If it seems too short or unclear, ask them to repeat it.

Family doctor:
- Ask whether the patient currently has a family doctor.
- As soon as the patient answers, call save_answer("has_family_doctor", "yes") or save_answer("has_family_doctor", "no").
- Always save "yes" or "no" — nothing else.
- If yes, then ask for the doctor's full name including first and last name.
- If the patient gives only a last name, ask for the first name too.
- Save the name in UPPERCASE.
- If the patient does not know the name, save "unknown".
- If no, skip the family doctor name and move on.

Psychiatrist:
- Ask whether the patient currently has a psychiatrist.
- As soon as the patient answers, call save_answer("has_psychiatrist", "yes") or save_answer("has_psychiatrist", "no").
- Always save "yes" or "no" — nothing else.
- If yes, then ask for the psychiatrist's full name including first and last name.
- If the patient gives only a last name, ask for the first name too.
- Save the name in UPPERCASE.
- If the patient does not know the name, save "unknown".
- If no, skip the psychiatrist name and move on.
""",

    "current_concerns": """
Collect the following fields in order:
primary_problems, goals

General rules:
- Let the patient answer in their own words.
- Do not diagnose, interpret, or provide therapy.
- If an answer is unclear, ask one short clarification.
- Always call save_answer as soon as the patient gives a clear response.
- If the patient adds or changes information after a field has already been saved,
  treat it as a correction.
- Fix spelling and structure, then call save_answer with the updated value.
- Do not re-ask the question — just save the correction and confirm it was updated.

Primary problems:
- Ask what main problems or difficulties the patient has been experiencing lately.
- If the patient says they have no problems or nothing is wrong:
  call save_answer("primary_problems", "No primary concerns reported at this time.")
- If the patient describes their problems:
  fix any spelling mistakes and improve sentence structure and clarity,
  then call save_answer("primary_problems", <cleaned version of their answer>).
  Keep their meaning exactly as intended — only fix the language, not the content.

Goals:
- Ask what the patient hopes to get out of their appointment.
- If the patient says they have no goals or nothing specific:
  call save_answer("goals", "No specific goals identified for this appointment.")
- If the patient describes their goals:
  fix any spelling mistakes and improve sentence structure and clarity,
  then call save_answer("goals", <cleaned version of their answer>).
  Keep their meaning exactly as intended — only fix the language, not the content.
""",

}
