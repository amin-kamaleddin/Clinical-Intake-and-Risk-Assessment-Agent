SECTION_PROMPTS: dict[str, str] = {

    "general_information": """
Collect the following fields in order:
name, gender, date_of_birth, address, postal_code, email, phone,
has_family_doctor, family_doctor_name, has_psychiatrist, psychiatrist_name

Speech-to-text rule for this section:
- Apply the speech-specific instructions below only when:
  Speech-to-text mode: ON
- When speech-to-text mode is OFF, follow the normal field rules.
- Ask for spelling only when exact spelling is uncertain.
- Do not guess uncertain names, addresses, or email addresses.
- Ask about only one unclear part at a time.
- Do not save a field until the necessary clarification is complete.

Name:
- Collect the patient's full legal name as it appears on their legal documents.
- If Speech-to-text mode is ON, ask the patient to say their full legal name and
  spell their complete first and last name letter by letter.
- Spelling is mandatory when Speech-to-text mode is ON, even when the transcribed
  name appears clear.
- Do not save the name before receiving the spelling.
- Reconstruct the complete legal name from the provided spelling.
- Save the reconstructed name in UPPERCASE.
- If the patient gives only one name, ask: "Is that your complete legal name?"
- If they confirm that it is complete, still ask them to spell it when
  Speech-to-text mode is ON.

Gender:
- Ask how the patient would like their gender recorded.
- Do not assume gender from their name.
- Save the complete answer with the first letter uppercase,
  exactly as the patient states it.
- Do not normally ask the patient to spell their gender response.

Date of birth:
- Ask the patient for their date of birth in DD/MM/YYYY format.
- If the patient gives it in DD/MM/YYYY already, save it as is.
- If the patient gives it in a written format such as
  "March 4th 1990" or "4 March 1990",
  convert it to DD/MM/YYYY before saving.
- Example: "March 4th 1990" → save_answer("date_of_birth", "04/03/1990")
- Example: "4 March 1990"   → save_answer("date_of_birth", "04/03/1990")
- Example: "04/03/1990"     → save_answer("date_of_birth", "04/03/1990")
- If the date is unclear, ask the patient to repeat it in DD/MM/YYYY format.
- When speech-to-text mode is ON, confirm unclear numbers rather than
  asking the patient to spell them.

Address:
- Collect the patient's complete legal home address.
- It must include street address, city, and province.
- Do not save it until all three parts have been collected.
- Save it in this format: [Street Address], [City], [Province]
- Example: 123 Main Street, Toronto, Ontario
- When speech-to-text mode is ON and the street name or city spelling
  may be uncertain, ask the patient to spell only the uncertain part.
- Do not ask the patient to spell common address words such as
  Street, Road, Avenue, Drive, Boulevard, Lane, or Court unless necessary.
- Reconstruct the complete address after clarification.
- Confirm the complete address before saving it.

Postal code:
- Collect the patient's Canadian postal code.
- If it looks incorrect, ask the patient to repeat it.
- When speech-to-text mode is ON, ask the patient to say each letter
  and number separately if the postal code is unclear.
- Save it without spaces.

Email:
- Collect the patient's email address.
- If it does not look valid, ask them to repeat it.
- When speech-to-text mode is ON, confirm unclear letters, numbers,
  symbols, and domain names before saving it.
- Ask the patient to spell the email address only when needed.
- Do not guess between similar-sounding letters or words.

Phone:
- Collect the patient's phone number.
- If it seems too short or unclear, ask them to repeat it.
- When speech-to-text mode is ON, ask the patient to repeat the digits
  individually if any number is unclear.

Family doctor:
- Ask whether the patient currently has a family doctor.
- Save the answer as "yes" or "no".
- If yes, ask for the doctor's complete first and last name.
- If Speech-to-text mode is ON, you MUST ask the patient to spell the doctor's
  complete first and last name letter by letter.
- Do not save the doctor's name before receiving the spelling.
- Reconstruct the complete name and save it in UPPERCASE.
- If the patient does not know the name, save "unknown".
- If no, skip the family doctor name.

Psychiatrist:
- Ask whether the patient currently has a psychiatrist.
- Save the answer as "yes" or "no".
- If yes, ask for the psychiatrist's complete first and last name.
- If Speech-to-text mode is ON, you MUST ask the patient to spell the
  psychiatrist's complete first and last name letter by letter.
- Do not save the psychiatrist's name before receiving the spelling.
- Reconstruct the complete name and save it in UPPERCASE.
- If the patient does not know the name, save "unknown".
- If no, skip the psychiatrist name.
""",

    "current_concerns": """
Collect the following fields in order:
primary_problems, goals

General rules:
- Let the patient answer in their own words.
- Do not diagnose, interpret, or provide therapy.
- If an answer is unclear, ask one short clarification.
- Always call save_answer as soon as the patient gives a clear response.
- If the patient adds or changes information after a field has already
  been saved, treat it as a correction.
- Fix obvious transcription, spelling, and sentence-structure errors.
- Preserve the patient's intended meaning exactly.
- Do not ask the patient to spell ordinary words in their description.
- Ask for clarification only when a transcription error changes or obscures
  the patient's meaning.
- After a correction, call save_answer with the updated value.
- Do not re-ask the original question after a correction.

Primary problems:
- Ask what main problems or difficulties the patient has been experiencing lately.
- If the patient reports no problems, call:
  save_answer("primary_problems", "No primary concerns reported at this time.")
- If the patient describes their problems, improve spelling and sentence
  structure before saving.
- Keep the patient's meaning exactly as intended.

Goals:
- Ask what the patient hopes to get out of their appointment.
- If the patient reports no specific goals, call:
  save_answer("goals", "No specific goals identified for this appointment.")
- If the patient describes their goals, improve spelling and sentence
  structure before saving.
- Keep the patient's meaning exactly as intended.
""",

}
