"""Emits messages.jsonl. Kept in the repo so the corpus is reproducible and
reviewable rather than a wall of opaque JSON."""
import json

W = ("whatsapp group", "student")      # class group chat      - authority 2
P = ("class announcement", "professor")  # said in class       - authority 4
PM = ("prof email", "professor")       # from the professor    - authority 4
T = ("TA email", "ta")                 # from a TA             - authority 3
L = ("LMS", "system")                  # official portal       - authority 4
C = ("college email", "system")        # institutional mail    - authority 4

M = [
    # ---- week of Aug 17 ------------------------------------------------
    ("2026-08-17T09:12", P, "Welcome back everyone. DBMS lectures shift to the 10am slot from this week."),
    ("2026-08-17T09:40", W, "bro send the notes from yesterday"),
    ("2026-08-17T11:02", L, "Maths-III Assignment 3 has been posted. Submission by 27 August, carries 10 marks."),
    ("2026-08-17T13:15", W, "anyone up for football at 6?"),
    ("2026-08-17T13:22", W, "im in"),
    ("2026-08-17T17:44", W, "wifi in the library is down again"),

    ("2026-08-18T10:05", T, "DBMS Assignment 2 (the ER-to-relational report) is due on the 28th. Weightage 20%."),  # ★ contradiction target
    ("2026-08-18T10:31", W, "20% is a lot for one report ugh"),
    ("2026-08-18T12:00", W, "is there class at 9 tmrw?"),
    ("2026-08-18T12:04", W, "no first hour is free"),
    ("2026-08-18T15:20", P, "Computer Networks lab record has to be submitted by the 31st, no extensions."),
    ("2026-08-18T18:50", W, "canteen bunk at 1?"),

    ("2026-08-19T09:05", P, "There will be a DBMS quiz on Wednesday next week. Units 1 and 2."),  # ★ correction target
    ("2026-08-19T09:33", W, "wait which units for the quiz"),
    ("2026-08-19T09:35", W, "1 and 2 he said"),
    ("2026-08-19T11:15", W, "who's coming to the fest on Saturday"),
    ("2026-08-19T14:02", C, "Registrations for the inter-college hackathon close on Sunday 30 August. Teams of four."),
    ("2026-08-19T16:40", W, "anyone selling a scientific calculator"),
    ("2026-08-19T20:10", W, "movie at 7:30 anyone"),

    ("2026-08-20T08:55", W, "CN assignment is due on Sept 2 I think"),   # ★ true contradiction, side A
    ("2026-08-20T09:10", W, "attendance kitna hai tumhara"),
    ("2026-08-20T10:25", PM, "Machine Learning project proposal - one page, due 7 September. This is 15% of your internals."),
    ("2026-08-20T12:48", W, "guys where is the CN class today"),
    ("2026-08-20T12:51", W, "lab 3, they shifted it"),
    ("2026-08-20T15:30", W, "the AC in lab 3 is not working"),
    ("2026-08-20T19:05", W, "happy birthday Aditya 🎉"),

    ("2026-08-21T09:15", P, "For the OS lab report - start working on it, submit soon. The exact date will be announced later."),  # ★ unknown deadline
    ("2026-08-21T09:48", W, "so when is the OS lab report actually due"),
    ("2026-08-21T09:50", W, "no idea he didnt say"),
    ("2026-08-21T11:30", L, "DAA quiz scheduled for 1 September during the second hour."),
    ("2026-08-21T14:12", W, "does anyone have the OS textbook pdf"),
    ("2026-08-21T16:00", W, "bus timing changed to 8:15 from Monday"),
    ("2026-08-21T21:20", W, "who all are going home this weekend"),

    ("2026-08-22T10:00", W, "CN assignment is on the 4th, thats what the TA told our batch"),  # ★ true contradiction, side B
    ("2026-08-22T10:14", W, "huh I had 2nd written down"),
    ("2026-08-22T11:45", W, "cricket match on Sunday 4pm, ground is booked"),
    ("2026-08-22T13:30", W, "lunch at 12:30?"),
    ("2026-08-22T18:00", W, "the fest lineup is out, check insta"),

    ("2026-08-23T10:20", W, "reminder guys hackathon registration closes this Sunday, form karo"),  # duplicate
    ("2026-08-23T12:00", W, "is the library open till 10 today"),
    ("2026-08-23T15:45", W, "prof was absent on friday no?"),
    ("2026-08-23T19:30", W, "great match yesterday 🔥"),

    ("2026-08-24T09:02", PM, "Correction to my earlier announcement: the DBMS quiz has been moved to Friday, not Wednesday."),  # ★ clean correction
    ("2026-08-24T09:40", W, "finally some breathing room"),
    ("2026-08-24T11:11", W, "guys the DBMS report is due 25th not 28th, thats what the notice says"),  # ★ weak-source correction quoting old value
    ("2026-08-24T11:14", W, "what?? i had 28th"),
    ("2026-08-24T11:20", W, "same, someone check with the TA"),
    ("2026-08-24T13:00", W, "I heard the DAA quiz got shifted to the 3rd"),  # ★ hearsay, must not move the date
    ("2026-08-24T14:30", L, "Minor project first review on 9 September. Slides plus a working demo."),
    ("2026-08-24T16:20", W, "anyone free at 5 for the group photo"),
    ("2026-08-24T18:00", W, "guys the lift is out of order again"),

    ("2026-08-25T08:30", W, "the placement talk was boring ngl"),
    ("2026-08-25T09:05", W, "don't forget the DBMS quiz this week"),  # detail only, no date
    ("2026-08-25T10:00", T, "Reminder: Maths-III Assignment 3 submission is on 27 August."),  # duplicate
    ("2026-08-25T11:30", W, "can someone share yesterdays DBMS notes"),
    ("2026-08-25T12:15", W, "still no date for the OS lab report btw"),
    ("2026-08-25T14:00", W, "anyone going for the workshop at 3"),

    # ---- filler: routine chatter and a few more real items ---------------
    ("2026-08-19T10:10", W, "the projector in 204 is broken"),
    ("2026-08-19T13:25", W, "who wants chai"),
    ("2026-08-20T08:15", W, "traffic is insane today gonna be late"),
    ("2026-08-20T17:35", W, "anyone has the CN lab manual soft copy"),
    ("2026-08-21T10:40", W, "why is the syllabus so long this sem"),
    ("2026-08-21T19:00", W, "badminton court booked at 7"),
    ("2026-08-22T09:20", W, "is the seminar attendance compulsory"),
    ("2026-08-22T14:50", W, "someone lost a blue water bottle in 301"),
    ("2026-08-23T08:45", W, "good morning all"),
    ("2026-08-23T17:10", W, "the mess food today was actually decent"),
    ("2026-08-24T08:20", W, "did anyone submit the feedback form"),
    ("2026-08-24T20:15", W, "sleeping, night guys"),
    ("2026-08-25T07:50", W, "raining heavily, carry umbrellas"),
    ("2026-08-18T09:30", L, "Library dues for the previous semester must be cleared by 5 September."),
    ("2026-08-19T15:05", C, "Scholarship application portal closes 10 September for eligible students."),
    ("2026-08-20T11:00", W, "which elective are you all taking next sem"),
    ("2026-08-21T13:40", W, "the new lab assistant seems nice"),
    ("2026-08-22T16:30", W, "does the 4th sem result come out this week"),
    ("2026-08-23T11:50", W, "anyone up for a study session in the library"),
    ("2026-08-24T10:45", W, "guys is CN class cancelled today"),
    ("2026-08-25T13:20", W, "printer in the xerox shop is down"),
    ("2026-08-17T16:00", W, "welcome back everyone hope you had a good break"),
    ("2026-08-18T20:40", W, "share the timetable pdf someone"),
    ("2026-08-25T15:00", W, "how many backlogs can you carry to 6th sem"),
]

with open("messages.jsonl", "w") as f:
    for received_at, (source, role), text in sorted(M):
        f.write(json.dumps({"text": text, "source": source,
                            "sender_role": role, "received_at": received_at}) + "\n")

print(f"{len(M)} messages -> messages.jsonl")
