"""Intent-routed offline templates + systems.

Two jobs:
  * `pick_template(prompt)` → ONE ModuleConfig dict (single-tool fallback / live seed).
  * `pick_system(prompt)`   → a LIST of ModuleConfig dicts. Broad prompts ("plan my
    Japan trip") return a coordinated SET; focused prompts return one.

A real Gemini key bypasses these for actual generation, but they remain the seed
that grounds it and the variety-rich fallback when offline. ~35 distinct styles,
each using the building blocks that make it *look* like what it is.
"""
from __future__ import annotations

import re


# --- component shorthands ---------------------------------------------------
def _t(id, label, ph=None):
    c = {"id": id, "type": "text_input", "label": label}
    if ph:
        c["placeholder"] = ph
    return c

def _n(id, label, unit=None):
    c = {"id": id, "type": "number_input", "label": label, "min": 0, "step": 1}
    if unit:
        c["unit"] = unit
    return c

def _chk(id, label):
    return {"id": id, "type": "checkbox", "label": label}

def _sl(id, label, lo=0, hi=100, step=1, unit=None):
    c = {"id": id, "type": "slider", "label": label, "min": lo, "max": hi, "step": step}
    if unit:
        c["unit"] = unit
    return c

def _pr(id, label, mx=100, bound=None):
    c = {"id": id, "type": "progress_bar", "label": label, "max": mx}
    if bound:
        c["bound_to"] = bound
    return c

def _li(id, label, item="Item", ph=None):
    c = {"id": id, "type": "list", "label": label, "item_label": item}
    if ph:
        c["placeholder"] = ph
    return c

def _kpi(id, label, unit=None):
    c = {"id": id, "type": "kpi", "label": label}
    if unit:
        c["unit"] = unit
    return c

def _rt(id, label, mx=5):
    return {"id": id, "type": "rating", "label": label, "max": mx}

def _tg(id, label):
    return {"id": id, "type": "tags", "label": label}

def _dt(id, label):
    return {"id": id, "type": "date", "label": label}

def _tbl(id, label, cols):
    return {"id": id, "type": "table", "label": label, "columns": cols}

def _cal(id, label):
    return {"id": id, "type": "calendar", "label": label}

def _ch(id, label, kind="bar", unit=None):
    c = {"id": id, "type": "chart", "label": label, "chart_type": kind}
    if unit:
        c["unit"] = unit
    return c

def _sec(id, label):
    return {"id": id, "type": "section", "label": label}

def _div(id="divider"):
    return {"id": id, "type": "divider", "label": ""}

def _kan(id, label, cols):
    return {"id": id, "type": "kanban", "label": label, "columns": cols}

def _hm(id, label, unit=None):
    c = {"id": id, "type": "heatmap", "label": label}
    if unit:
        c["unit"] = unit
    return c

def _ga(id, label, lo=0, hi=100, unit=None):
    c = {"id": id, "type": "gauge", "label": label, "min": lo, "max": hi}
    if unit:
        c["unit"] = unit
    return c

def _ckl(id, label):
    return {"id": id, "type": "checklist", "label": label}

def _gal(id, label):
    return {"id": id, "type": "gallery", "label": label}

def _note(id, label, ph=None):
    c = {"id": id, "type": "note", "label": label}
    if ph:
        c["placeholder"] = ph
    return c


def _mod(title, icon, accent, components, summary=None, columns=1):
    m = {"title": title, "icon": icon, "accent": accent, "components": components}
    if summary:
        m["summary_component_id"] = summary
    if columns and columns != 1:
        m["columns"] = columns
    return m


# --- single-tool templates (each a distinct visual style) -------------------
def _workout():
    return _mod("Workout Log", "🏋️", "emerald", [
        _t("exercise", "Exercise", "e.g. Bench press"),
        _n("sets", "Sets"), _n("reps", "Reps"),
        _sl("weight", "Weight", 0, 315, 5, "lb"),
        _chk("done", "Done today"),
        _pr("weekly", "Weekly sessions", 5, "sets"),
    ], "weekly")

def _calorie():
    return _mod("Calorie Tracker", "🍎", "coral", [
        _li("meals", "Meals today", "Meal", "e.g. Oatmeal — 320 cal"),
        _n("calories", "Calories so far", "cal"),
        _pr("goal", "Daily goal (2000)", 2000, "calories"),
        _n("water", "Water", "glasses"),
    ], "goal")

def _budget():
    return _mod("Budget", "💰", "amber", [
        _kpi("remaining", "Remaining", "$"),
        _ch("by_category", "Spending by category", "pie", "$"),
        _tbl("expenses", "Expenses", ["Item", "Category", "Amount"]),
        _pr("used", "Budget used", 2000),
    ], "remaining")

def _todo():
    return _mod("To-Do List", "✅", "sky", [
        _li("tasks", "Tasks", "Task", "Add a task…"),
        _n("done_count", "Completed today"),
        _pr("progress", "Daily target", 10, "done_count"),
    ], "progress")

def _reading():
    return _mod("Reading List", "📚", "violet", [
        _tbl("books", "Books", ["Title", "Author", "Status"]),
        _t("current", "Currently reading", "Title"),
        _pr("book_progress", "Toward book (350 pp)", 350),
        _rt("rating", "Last book rating"),
    ], "book_progress")

def _habit():
    return _mod("Habit Tracker", "🔁", "teal", [
        _t("habit", "Habit", "e.g. Meditate"),
        _cal("days", "Days done"),
        _n("streak", "Current streak", "days"),
        _pr("month", "30-day goal", 30, "streak"),
    ], "month")

def _mood():
    return _mod("Mood Journal", "🌙", "rose", [
        _t("entry", "Today", "How was your day?"),
        _sl("mood", "Mood", 1, 10, 1),
        _tg("tags", "Tags"),
        _li("gratitude", "Grateful for", "Item"),
    ], "mood")

def _calendar_tool():
    return _mod("Calendar", "🗓️", "sky", [
        _cal("days", "This month"),
        _li("events", "Upcoming", "Event", "e.g. Dentist — Fri 3pm"),
    ], "days")

def _schedule():
    return _mod("Weekly Schedule", "🗓️", "violet", [
        _tbl("slots", "Schedule", ["Day", "Time", "Activity"]),
        _cal("days", "Month view"),
    ])

def _weight():
    return _mod("Weight Tracker", "⚖️", "emerald", [
        _kpi("current", "Current", "lb"),
        _ch("trend", "Trend", "line", "lb"),
        _n("goal", "Goal", "lb"),
        _pr("toward", "Toward goal", 200),
    ], "current")

def _sleep():
    return _mod("Sleep Tracker", "😴", "violet", [
        _ch("hours", "Hours slept", "area", "h"),
        _sl("quality", "Last night quality", 1, 10, 1),
        _kpi("avg", "Avg this week", "h"),
    ], "avg")

def _water():
    return _mod("Water Intake", "💧", "sky", [
        _n("glasses", "Glasses today"),
        _pr("goal", "Daily goal (8)", 8, "glasses"),
        _cal("days", "Days hit goal"),
    ], "goal")

def _savings():
    return _mod("Savings Goal", "🐷", "emerald", [
        _t("goal_name", "Saving for", "e.g. New laptop"),
        _kpi("saved", "Saved", "$"),
        _pr("progress", "Toward goal", 1000, "saved"),
        _ch("monthly", "Monthly deposits", "bar", "$"),
    ], "progress")

def _expenses():
    return _mod("Spending Tracker", "🧾", "amber", [
        _tbl("tx", "Transactions", ["Date", "Merchant", "Category", "Amount"]),
        _ch("by_month", "By month", "bar", "$"),
        _kpi("total", "This month", "$"),
    ], "total")

def _subscriptions():
    return _mod("Subscriptions", "🔁", "coral", [
        _tbl("subs", "Subscriptions", ["Service", "Cost", "Renews"]),
        _kpi("monthly", "Monthly total", "$"),
    ], "monthly")

def _project():
    return _mod("Project Tracker", "📁", "sky", [
        _tbl("tasks", "Tasks", ["Task", "Owner", "Status"]),
        _pr("done", "Completion", 100),
        _li("milestones", "Milestones", "Milestone"),
    ])

def _class_schedule():
    return _mod("Class Schedule", "🎓", "violet", [
        _tbl("classes", "Classes", ["Course", "Day", "Time", "Room"]),
        _cal("days", "Term calendar"),
    ])

def _assignments():
    return _mod("Assignment Tracker", "📝", "coral", [
        _tbl("items", "Assignments", ["Course", "Assignment", "Due", "Status"]),
        _pr("done", "Completed", 100),
    ])

def _grades():
    return _mod("Grades", "🎯", "amber", [
        _kpi("gpa", "GPA"),
        _tbl("courses", "Courses", ["Course", "Grade", "Credits"]),
        _ch("trend", "Grade trend", "line"),
    ], "gpa")

def _recipe():
    return _mod("Recipe", "🍳", "coral", [
        _t("name", "Dish", "e.g. Carbonara"),
        _li("ingredients", "Ingredients", "Ingredient"),
        _li("steps", "Steps", "Step"),
        _rt("rating", "Rating"),
    ])

def _meal_plan():
    return _mod("Meal Planner", "🍽️", "emerald", [
        _tbl("plan", "This week", ["Day", "Breakfast", "Lunch", "Dinner"]),
        _li("groceries", "Groceries", "Item"),
    ])

def _watchlist():
    return _mod("Watchlist", "🎬", "violet", [
        _tbl("items", "To watch", ["Title", "Type", "Where"]),
        _rt("rating", "Last watched rating"),
        _tg("genres", "Genres"),
    ])

def _music_practice():
    return _mod("Practice Log", "🎸", "rose", [
        _cal("days", "Practice days"),
        _n("minutes", "Minutes today", "min"),
        _li("pieces", "Working on", "Piece"),
        _pr("weekly", "Weekly goal (300m)", 300, "minutes"),
    ], "weekly")

def _language():
    return _mod("Language Learning", "🗣️", "sky", [
        _cal("days", "Streak"),
        _n("words", "New words today"),
        _pr("goal", "Daily words (20)", 20, "words"),
        _tg("topics", "Topics"),
    ], "goal")

def _job_search():
    return _mod("Job Applications", "💼", "teal", [
        _tbl("apps", "Applications", ["Company", "Role", "Status", "Date"]),
        _kpi("sent", "Applications sent"),
        _ch("by_status", "By status", "pie"),
    ], "sent")

def _contacts():
    return _mod("Contacts", "📇", "sky", [
        _tbl("people", "People", ["Name", "Phone", "Email", "Notes"]),
        _tg("groups", "Groups"),
    ])

def _inventory():
    return _mod("Inventory", "📦", "amber", [
        _tbl("items", "Items", ["Item", "Qty", "Location"]),
        _kpi("count", "Total items"),
    ], "count")

def _plants():
    return _mod("Plant Care", "🌱", "emerald", [
        _tbl("plants", "Plants", ["Plant", "Water every", "Last watered"]),
        _cal("watered", "Watered days"),
    ])

def _pets():
    return _mod("Pet Care", "🐾", "coral", [
        _t("pet", "Pet", "e.g. Luna"),
        _chk("fed", "Fed today"),
        _chk("walked", "Walked today"),
        _cal("vet", "Vet / grooming"),
    ])

def _goals():
    return _mod("Goals", "⭐", "gold", [
        _tbl("goals", "Goals", ["Goal", "By when", "Progress"]),
        _pr("overall", "Overall", 100),
    ])

def _steps():
    return _mod("Step Counter", "👟", "emerald", [
        _ch("daily", "Daily steps", "bar"),
        _kpi("today", "Today", "steps"),
        _pr("goal", "Goal (10k)", 10000, "today"),
    ], "goal")

def _medication():
    return _mod("Medication", "💊", "rose", [
        _tbl("meds", "Medications", ["Name", "Dose", "Time"]),
        _cal("taken", "Taken days"),
    ])

def _cleaning():
    return _mod("Cleaning Schedule", "🧹", "teal", [
        _tbl("chores", "Chores", ["Task", "Frequency", "Who"]),
        _cal("done", "Done days"),
    ])

def _events():
    return _mod("Event Reminders", "🎉", "rose", [
        _tbl("events", "Events", ["Event", "Date", "Notes"]),
        _dt("next", "Next up"),
    ])

def _invoices():
    return _mod("Invoices", "🧾", "teal", [
        _tbl("invoices", "Invoices", ["Client", "Amount", "Status"]),
        _kpi("outstanding", "Outstanding", "$"),
        _ch("monthly", "Monthly revenue", "bar", "$"),
    ], "outstanding")


# ===========================================================================
# Varied-format templates (boards, dashboards, heatmaps, journals, planners).
# These use the richer component library and 2-column layouts so the output
# isn't always a single vertical form.
# ===========================================================================

# --- Boards (kanban) -------------------------------------------------------
def _task_board():
    return _mod("Task Board", "grid", "sky", [
        _kan("board", "Tasks", ["Backlog", "To do", "Doing", "Done"]),
        _kpi("done", "Done this week"),
    ], "board")

def _sprint_board():
    return _mod("Sprint Board", "repeat", "violet", [
        _kan("board", "Sprint", ["To do", "In progress", "Review", "Done"]),
        _sl("velocity", "Capacity (points)", 0, 60, 1),
    ], "board")

def _crm():
    return _mod("Sales Pipeline", "briefcase", "emerald", [
        _kan("pipeline", "Deals", ["Lead", "Contacted", "Proposal", "Won", "Lost"]),
        _kpi("value", "Pipeline value", "$"),
    ], "pipeline")

def _job_board():
    return _mod("Job Search Board", "briefcase", "teal", [
        _kan("board", "Applications", ["Wishlist", "Applied", "Interview", "Offer"]),
        _kpi("sent", "Applied"),
    ], "board")

def _content_board():
    return _mod("Content Calendar", "calendar", "coral", [
        _kan("pipeline", "Pipeline", ["Idea", "Draft", "Scheduled", "Published"]),
        _cal("dates", "Schedule"),
    ], "pipeline", columns=2)

def _bug_tracker():
    return _mod("Bug Tracker", "target", "rose", [
        _kan("board", "Issues", ["Open", "In progress", "Testing", "Fixed"]),
        _kpi("open", "Open bugs"),
    ], "board")

def _flashcards():
    return _mod("Flashcards", "cap", "violet", [
        _kan("deck", "Cards", ["New", "Learning", "Almost", "Known"]),
        _hm("reviews", "Reviews"),
    ], "deck")

def _idea_board():
    return _mod("Idea Board", "sparkles", "gold", [
        _kan("ideas", "Ideas", ["Spark", "Exploring", "Building", "Shipped"]),
        _note("notes", "Scratchpad", "Capture a thought…"),
    ], "ideas")

def _shopping_board():
    return _mod("Shopping by Store", "cart", "amber", [
        _kan("stores", "Lists", ["Grocery", "Pharmacy", "Hardware", "Other"]),
    ], "stores")

def _workflow_board():
    return _mod("Workflow", "repeat", "sky", [
        _kan("flow", "Stages", ["Inbox", "Next", "Waiting", "Done"]),
        _kpi("count", "In flight"),
    ], "flow")


# --- Heatmaps / streaks ----------------------------------------------------
def _habit_grid():
    return _mod("Habit Grid", "repeat", "emerald", [
        _t("habit", "Habit", "e.g. Meditate"),
        _hm("days", "Daily check-ins"),
        _kpi("streak", "Current streak", "days"),
        _ckl("today", "Today's habits"),
    ], "days")

def _mood_heatmap():
    return _mod("Mood Heatmap", "smile", "rose", [
        _hm("mood", "Daily mood"),
        _ch("trend", "Trend", "line"),
        _note("note", "What shaped today?"),
    ], "mood", columns=2)

def _meditation():
    return _mod("Meditation", "moon", "violet", [
        _hm("days", "Sessions"),
        _ga("minutes", "Today (min)", 0, 60, "min"),
        _kpi("streak", "Streak", "days"),
    ], "days")

def _writing_streak():
    return _mod("Writing Streak", "pen", "sky", [
        _hm("days", "Days written"),
        _ga("words", "Today's words", 0, 2000, "words"),
        _note("scratch", "Draft", "Start writing…"),
    ], "days", columns=2)

def _running_log():
    return _mod("Running Log", "activity", "emerald", [
        _hm("days", "Run days"),
        _tbl("runs", "Runs", ["Date", "Distance", "Pace", "Notes"]),
        _ch("mileage", "Weekly miles", "bar", "mi"),
    ], "days", columns=2)

def _language_streak():
    return _mod("Language Streak", "cap", "sky", [
        _hm("days", "Practice days"),
        _tbl("vocab", "New words", ["Word", "Meaning"]),
        _ga("daily", "Today's words", 0, 30),
    ], "days", columns=2)

def _meals_log():
    return _mod("Food Diary", "leaf", "coral", [
        _hm("days", "Logged days"),
        _tbl("meals", "Today", ["Meal", "Item", "Calories"]),
        _ga("calories", "Calories", 0, 2500, "cal"),
    ], "days", columns=2)


# --- Dashboards (2-column) -------------------------------------------------
def _life_dashboard():
    return _mod("Life Dashboard", "grid", "amber", [
        _kpi("focus", "Today's focus"),
        _ga("energy", "Energy", 0, 10),
        _pr("habits", "Habits done", 5),
        _ch("week", "This week", "bar"),
        _ckl("top3", "Top 3 today"),
    ], columns=2)

def _finance_dashboard():
    return _mod("Finance Dashboard", "dollar", "emerald", [
        _kpi("networth", "Net worth", "$"),
        _ga("budget", "Budget used", 0, 100, "%"),
        _ch("spend", "Spending by month", "bar", "$"),
        _tbl("accounts", "Accounts", ["Account", "Balance"]),
    ], columns=2)

def _fitness_dashboard():
    return _mod("Fitness Dashboard", "activity", "emerald", [
        _kpi("workouts", "Workouts this week"),
        _ga("readiness", "Readiness", 0, 100, "%"),
        _ch("weight", "Weight", "line", "lb"),
        _hm("days", "Active days"),
    ], columns=2)

def _sleep_dashboard():
    return _mod("Sleep Dashboard", "moon", "violet", [
        _ga("score", "Last night score", 0, 100),
        _kpi("avg", "Avg hours", "h"),
        _ch("hours", "Hours slept", "area", "h"),
        _hm("days", "Nights logged"),
    ], columns=2)

def _startup_dashboard():
    return _mod("Startup Metrics", "briefcase", "sky", [
        _kpi("mrr", "MRR", "$"),
        _kpi("users", "Active users"),
        _ch("growth", "Growth", "line"),
        _tbl("goals", "This quarter", ["Goal", "Target", "Now"]),
    ], columns=2)

def _creator_dashboard():
    return _mod("Creator Dashboard", "camera", "rose", [
        _kpi("followers", "Followers"),
        _ga("goal", "Monthly goal", 0, 100, "%"),
        _ch("views", "Views", "bar"),
        _tbl("posts", "Posts", ["Post", "Date", "Views"]),
    ], columns=2)

def _health_dashboard():
    return _mod("Health Dashboard", "heart", "coral", [
        _ga("hydration", "Hydration", 0, 8, "cups"),
        _kpi("steps", "Steps today"),
        _ch("weight", "Weight", "line", "lb"),
        _hm("days", "Active days"),
    ], columns=2)


# --- Journals / notes ------------------------------------------------------
def _daily_journal():
    return _mod("Daily Journal", "book", "rose", [
        _dt("date", "Date"),
        _sl("mood", "Mood", 1, 10, 1),
        _note("entry", "Today", "How did today go?"),
        _li("grateful", "Grateful for", "Item"),
        _tg("tags", "Tags"),
    ], columns=2)

def _gratitude_journal():
    return _mod("Gratitude", "heart", "gold", [
        _note("today", "Three good things", "What went well today?"),
        _hm("days", "Days journaled"),
    ], "days")

def _decision_log():
    return _mod("Decision Log", "target", "sky", [
        _tbl("decisions", "Decisions", ["Decision", "Why", "Outcome"]),
        _note("reflect", "Reflection"),
    ])

def _one_line():
    return _mod("One Line a Day", "pen", "amber", [
        _note("line", "Today in a line", "One sentence about today…"),
        _hm("days", "Days"),
    ], "days")

def _brain_dump():
    return _mod("Brain Dump", "sparkles", "teal", [
        _note("dump", "Everything on your mind", "Just write it all out…"),
        _ckl("actions", "Pulled-out actions"),
        _tg("themes", "Themes"),
    ])


# --- Planners / checklists -------------------------------------------------
def _trip_planner():
    return _mod("Trip Planner", "plane", "sky", [
        _cal("days", "Itinerary"),
        _ckl("packing", "Packing"),
        _tbl("budget", "Budget", ["Item", "Cost"]),
        _gal("inspo", "Inspiration"),
    ], columns=2)

def _wedding_planner():
    return _mod("Wedding Planner", "heart", "rose", [
        _sec("guests_sec", "Guests"),
        _tbl("guests", "Guest list", ["Name", "RSVP", "Table"]),
        _sec("plan_sec", "Plan"),
        _ckl("todo", "To do"),
        _ga("budget", "Budget used", 0, 100, "%"),
    ], columns=2)

def _move_planner():
    return _mod("Moving Planner", "home", "amber", [
        _ckl("tasks", "Moving checklist"),
        _cal("days", "Timeline"),
        _tbl("costs", "Costs", ["Item", "Cost"]),
        _ga("budget", "Budget used", 0, 100, "%"),
    ], columns=2)

def _event_planner():
    return _mod("Event Planner", "star", "coral", [
        _tl("timeline", "Run of show"),
        _tbl("guests", "Guests", ["Name", "RSVP"]),
        _ckl("todo", "To do"),
        _ga("budget", "Budget used", 0, 100, "%"),
    ], columns=2)

def _study_plan():
    return _mod("Study Plan", "cap", "violet", [
        _cal("days", "Study calendar"),
        _ckl("topics", "Topics to cover"),
        _ga("progress", "Course progress", 0, 100, "%"),
        _tbl("exams", "Exams", ["Subject", "Date"]),
    ], columns=2)

def _project_plan():
    return _mod("Project Plan", "folder", "sky", [
        _sec("board_sec", "Work"),
        _kan("board", "Tasks", ["To do", "Doing", "Done"]),
        _sec("plan_sec", "Plan"),
        _tl("milestones", "Milestones"),
        _ckl("launch", "Launch checklist"),
    ])

def _packing_list():
    return _mod("Packing List", "check", "sky", [
        _sec("ess", "Essentials"),
        _ckl("essentials", "Essentials"),
        _sec("clothes", "Clothes"),
        _ckl("clothing", "Clothing"),
    ])

def _onboarding():
    return _mod("New Job Onboarding", "briefcase", "teal", [
        _sec("wk1", "Week 1"),
        _ckl("week1", "First week"),
        _sec("setup", "Setup"),
        _ckl("accounts", "Accounts & access"),
        _note("notes", "Notes"),
    ])

def _skincare():
    return _mod("Skincare Routine", "droplet", "rose", [
        _sec("am", "Morning"),
        _ckl("morning", "AM routine"),
        _sec("pm", "Evening"),
        _ckl("evening", "PM routine"),
        _hm("days", "Consistency"),
    ], columns=2)

def _cleaning_rota():
    return _mod("Cleaning Rota", "check", "teal", [
        _kan("rooms", "By room", ["Kitchen", "Bath", "Bedroom", "Living"]),
        _hm("days", "Days cleaned"),
    ], "rooms")


# --- Money trackers (gauges / progress) ------------------------------------
def _budget_envelopes():
    return _mod("Budget Envelopes", "dollar", "emerald", [
        _ga("groceries", "Groceries", 0, 400, "$"),
        _ga("dining", "Dining", 0, 200, "$"),
        _ga("transport", "Transport", 0, 150, "$"),
        _ga("fun", "Fun", 0, 150, "$"),
        _kpi("left", "Left this month", "$"),
    ], columns=2)

def _debt_payoff():
    return _mod("Debt Payoff", "dollar", "coral", [
        _tbl("debts", "Debts", ["Name", "Balance", "APR"]),
        _pr("progress", "Paid off", 100),
        _kpi("remaining", "Remaining", "$"),
        _ch("paid", "Paid by month", "bar", "$"),
    ], columns=2)

def _savings_goals():
    return _mod("Savings Goals", "dollar", "emerald", [
        _t("goal1", "Goal 1", "e.g. Emergency fund"),
        _ring("r1", "Goal 1 progress", 5000),
        _t("goal2", "Goal 2", "e.g. Vacation"),
        _ring("r2", "Goal 2 progress", 2000),
    ], columns=2)

def _net_worth():
    return _mod("Net Worth", "dollar", "sky", [
        _kpi("total", "Net worth", "$"),
        _ch("trend", "Over time", "area", "$"),
        _tbl("assets", "Assets & debts", ["Item", "Value"]),
    ], "total")


# --- Life trackers (varied) ------------------------------------------------
def _car_maintenance():
    return _mod("Car Maintenance", "target", "sky", [
        _ga("mileage", "Mileage", 0, 200000, "mi"),
        _tbl("log", "Service log", ["Date", "Service", "Cost"]),
        _ckl("checks", "Routine checks"),
    ], columns=2)

def _garden_planner():
    return _mod("Garden Planner", "leaf", "emerald", [
        _tbl("beds", "Beds", ["Plant", "Bed", "Planted"]),
        _cal("dates", "Planting calendar"),
        _hm("watered", "Watering"),
    ], columns=2)

def _pet_care():
    return _mod("Pet Care", "paw", "coral", [
        _sec("daily", "Daily"),
        _ckl("routine", "Daily routine"),
        _tl("vet", "Vet & grooming"),
        _gal("photos", "Photos"),
    ], columns=2)

def _baby_log():
    return _mod("Baby Log", "heart", "rose", [
        _tbl("feeds", "Feeds", ["Time", "Type", "Amount"]),
        _ch("sleep", "Sleep (h)", "bar", "h"),
        _kpi("diapers", "Diapers today"),
    ], columns=2)

def _cycle_tracker():
    return _mod("Cycle Tracker", "calendar", "rose", [
        _cal("days", "Cycle"),
        _ch("symptoms", "Symptoms", "line"),
        _note("notes", "Notes"),
    ], "days")

def _symptom_tracker():
    return _mod("Symptom Tracker", "heart", "coral", [
        _hm("days", "Flare days"),
        _ch("severity", "Severity", "line"),
        _note("notes", "Triggers & notes"),
    ], "days", columns=2)


# --- Wishlists / collections (galleries) -----------------------------------
def _wishlist():
    return _mod("Wishlist", "star", "gold", [
        _gal("items", "Wishlist"),
        _tbl("details", "Details", ["Item", "Price", "Link"]),
        _rt("priority", "Top pick rating"),
    ], columns=2)

def _restaurants():
    return _mod("Restaurants to Try", "leaf", "coral", [
        _tbl("places", "Places", ["Name", "Cuisine", "Area"]),
        _rt("rating", "Last visit"),
        _tg("tags", "Cravings"),
        _gal("dishes", "Dishes"),
    ], columns=2)

def _bucket_list():
    return _mod("Bucket List", "star", "sky", [
        _ckl("list", "Bucket list"),
        _gal("inspo", "Inspiration"),
        _tg("themes", "Themes"),
    ], columns=2)

def _moodboard():
    return _mod("Moodboard", "camera", "violet", [
        _gal("images", "Moodboard"),
        _tg("palette", "Vibe"),
        _note("notes", "Direction"),
    ], "images")


# --- Thinking tools --------------------------------------------------------
def _weekly_retro():
    return _mod("Weekly Retro", "repeat", "violet", [
        _sec("good", "What went well"),
        _li("went_well", "Wins", "Win"),
        _sec("improve", "What to improve"),
        _li("improve_list", "Improve", "Item"),
        _sec("act", "Actions"),
        _ckl("actions", "Next week"),
    ], columns=2)

def _okrs():
    return _mod("Quarterly OKRs", "target", "amber", [
        _t("objective", "Objective", "What are we aiming for?"),
        _pr("kr1", "Key result 1", 100),
        _pr("kr2", "Key result 2", 100),
        _pr("kr3", "Key result 3", 100),
        _kpi("score", "Overall", "%"),
    ], columns=2)

def _pros_cons():
    return _mod("Pros & Cons", "target", "sky", [
        _li("pros", "Pros", "Pro"),
        _li("cons", "Cons", "Con"),
        _note("decision", "Decision"),
    ], columns=2)

def _decision_matrix():
    return _mod("Decision Matrix", "grid", "violet", [
        _tbl("matrix", "Options", ["Option", "Cost", "Value", "Score"]),
        _note("notes", "Notes"),
    ], "matrix")


def _ring(id, label, mx=100):
    return {"id": id, "type": "ring", "label": label, "max": mx}


def _tl(id, label):
    return {"id": id, "type": "timeline", "label": label}


def _generic(prompt: str) -> dict:
    title = _clean_title(prompt)
    icon, accent = _visual_for(prompt)
    return _mod(title, icon, accent, [
        _t("name", "Name", title),
        _li("items", "Items", "Item", "Add an item…"),
        _n("count", "Count"),
        _t("notes", "Notes", "Anything to remember"),
    ], "count")


# --- routing ----------------------------------------------------------------
# Varied-format routes — checked BEFORE the originals so richer formats win.
_ROUTES_V2: list[tuple[tuple[str, ...], object]] = [
    (("kanban", "task board", "backlog"), _task_board),
    (("sprint", "scrum", "agile"), _sprint_board),
    (("sales pipeline", "crm", "leads", "deals"), _crm),
    (("job board", "application board"), _job_board),
    (("content calendar", "editorial", "posting"), _content_board),
    (("bug", "issue tracker", "defect"), _bug_tracker),
    (("flashcard", "spaced repetition", "anki"), _flashcards),
    (("idea board", "brainstorm"), _idea_board),
    (("shopping by store", "grocery board"), _shopping_board),
    (("workflow", "pipeline"), _workflow_board),
    (("habit grid", "habit heatmap", "habit tracker"), _habit_grid),
    (("mood",), _mood_heatmap),
    (("meditat", "mindful"), _meditation),
    (("writing", "write every"), _writing_streak),
    (("running", "run log", "jog", "marathon"), _running_log),
    (("language", "vocab", "spanish", "french"), _language_streak),
    (("food diary",), _meals_log),
    (("life dashboard", "daily overview", "life overview"), _life_dashboard),
    (("finance dashboard", "money dashboard"), _finance_dashboard),
    (("fitness dashboard",), _fitness_dashboard),
    (("sleep",), _sleep_dashboard),
    (("startup", "mrr", "saas"), _startup_dashboard),
    (("creator", "influencer", "social media"), _creator_dashboard),
    (("health dashboard",), _health_dashboard),
    (("daily journal", "journal", "diary"), _daily_journal),
    (("gratitude",), _gratitude_journal),
    (("decision log",), _decision_log),
    (("one line", "one-line"), _one_line),
    (("brain dump", "braindump"), _brain_dump),
    (("trip planner", "travel", "vacation", "itinerary"), _trip_planner),
    (("wedding", "marriage"), _wedding_planner),
    (("moving", "move house", "relocat"), _move_planner),
    (("event plan", "party plan"), _event_planner),
    (("study plan", "exam", "revision"), _study_plan),
    (("project plan", "project board", "roadmap", "project"), _project_plan),
    (("packing", "pack list"), _packing_list),
    (("onboarding",), _onboarding),
    (("skincare", "skin routine"), _skincare),
    (("cleaning rota", "chore chart", "cleaning schedule"), _cleaning_rota),
    (("envelope", "budget categor"), _budget_envelopes),
    (("debt", "loan payoff", "payoff"), _debt_payoff),
    (("savings goal", "save for", "saving"), _savings_goals),
    (("net worth", "networth"), _net_worth),
    (("car", "vehicle", "maintenance"), _car_maintenance),
    (("garden",), _garden_planner),
    (("pet", "dog", "cat"), _pet_care),
    (("baby", "newborn", "infant"), _baby_log),
    (("cycle", "period", "menstru"), _cycle_tracker),
    (("symptom", "chronic", "flare"), _symptom_tracker),
    (("wishlist", "wish list"), _wishlist),
    (("restaurant", "places to eat", "food spots"), _restaurants),
    (("bucket list",), _bucket_list),
    (("moodboard", "mood board", "inspiration board"), _moodboard),
    (("retro", "retrospective", "weekly review"), _weekly_retro),
    (("okr", "objectives", "key results"), _okrs),
    (("pros and cons", "pros & cons", "pro con", "pros cons"), _pros_cons),
    (("decision matrix", "compare options", "weighted"), _decision_matrix),
]

# keyword tuple -> single-template builder. First match wins.
_ROUTES: list[tuple[tuple[str, ...], object]] = [
    (("workout", "exercise", "gym", "lift", "fitness", "training"), _workout),
    (("calorie", "food log", "nutrition", "diet", "macro", "meal log"), _calorie),
    (("meal plan", "meal planner", "weekly meals"), _meal_plan),
    (("subscription",), _subscriptions),
    (("invoice",), _invoices),
    (("budget", "expense", "spend", "money", "cost", "finance"), _budget),
    (("saving", "save up", "savings"), _savings),
    (("todo", "to-do", "task", "checklist", "chore"), _todo),
    (("read", "book", "reading"), _reading),
    (("habit", "streak", "routine"), _habit),
    (("mood", "journal", "gratitude", "feeling", "diary"), _mood),
    (("calendar",), _calendar_tool),
    (("schedule", "timetable"), _schedule),
    (("weight",), _weight),
    (("sleep",), _sleep),
    (("water", "hydrat"), _water),
    (("class", "course", "lecture"), _class_schedule),
    (("assignment", "homework"), _assignments),
    (("grade", "gpa"), _grades),
    (("recipe", "cook"), _recipe),
    (("watchlist", "watch list", "movie", "film", "show", "tv"), _watchlist),
    (("practice", "guitar", "piano", "instrument", "music"), _music_practice),
    (("language", "vocab", "spanish", "french", "japanese learn"), _language),
    (("job", "application", "interview", "career"), _job_search),
    (("contact", "address book"), _contacts),
    (("inventory", "stock"), _inventory),
    (("plant", "garden"), _plants),
    (("pet", "dog", "cat"), _pets),
    (("goal",), _goals),
    (("step",), _steps),
    (("medication", "medicine", "pill", "meds"), _medication),
    (("cleaning", "clean"), _cleaning),
    (("event", "reminder", "birthday"), _events),
    (("project",), _project),
]

# keyword tuple -> list of template builders forming a coordinated system.
_SYSTEM_ROUTES: list[tuple[tuple[str, ...], list[object]]] = [
    (("trip", "travel", "vacation", "holiday", "japan", "europe", "flight"),
     [_calendar_tool, _budget, _todo, _reading]),
    (("wedding", "marriage"),
     [_contacts, _budget, _calendar_tool, _events]),
    (("semester", "school", "college", "university", "study"),
     [_class_schedule, _assignments, _grades, _habit]),
    (("moving", "move house", "relocat", "new apartment"),
     [_todo, _budget, _contacts, _calendar_tool]),
    (("business", "freelance", "startup", "side hustle", "clients"),
     [_job_search, _invoices, _todo, _savings]),
    (("baby", "newborn", "pregnan"),
     [_meal_plan, _sleep, _goals, _todo]),
    (("get fit", "fitness journey", "lose weight", "gym plan", "health journey"),
     [_workout, _calorie, _weight, _water]),
    (("party", "event planning", "birthday party", "celebration"),
     [_contacts, _budget, _calendar_tool, _todo]),
    (("renovation", "remodel", "home project"),
     [_budget, _project, _calendar_tool]),
    (("new year", "resolutions", "this year"),
     [_goals, _habit, _budget]),
]

_FILLER = {
    "a", "an", "the", "my", "to", "for", "of", "i", "want", "need",
    "create", "make", "build", "track", "tracker", "tracking", "something",
    "that", "keeps", "keep", "help", "me", "with", "organize", "plan", "planner",
}


def _clean_title(prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+", prompt)
    kept = [w for w in words if w.lower() not in _FILLER]
    chosen = (kept or words)[:4]
    if not chosen:
        return "Workspace"
    return " ".join(w.capitalize() for w in chosen)


_GENERIC_ACCENTS = ("amber", "emerald", "sky", "rose", "violet", "coral", "teal", "gold")
_GENERIC_ICONS = ("🗂️", "📝", "📌", "🧭", "🎯", "📦", "🗓️", "⭐")


def _visual_for(prompt: str) -> tuple[str, str]:
    h = sum(ord(ch) for ch in prompt.strip().lower()) if prompt.strip() else 0
    return _GENERIC_ICONS[h % len(_GENERIC_ICONS)], _GENERIC_ACCENTS[h % len(_GENERIC_ACCENTS)]


def _matches(keyword: str, text: str) -> bool:
    kw = re.escape(keyword)
    # Short keywords ("cat", "car", "pet") must be whole words (+ optional plural)
    # so they don't fire mid-word ("category", "career"). Longer ones still match
    # suffixes ("workout" -> "workouts", "read" -> "reading").
    pattern = rf"\b{kw}s?\b" if len(keyword) <= 3 else rf"\b{kw}"
    return re.search(pattern, text) is not None


def _finalize(config: dict) -> dict:
    config.setdefault("state", {})
    config.setdefault("layout", {"x": 80, "y": 120, "width": 380, "height": 460})
    return config


def pick_template(prompt: str) -> dict:
    """Return ONE full ModuleConfig dict for the given prompt."""
    lower = prompt.lower()
    for keywords, builder in (*_ROUTES_V2, *_ROUTES):
        if any(_matches(k, lower) for k in keywords):
            return _finalize(builder())  # type: ignore[operator]
    return _finalize(_generic(prompt))


def pick_system(prompt: str) -> list[dict]:
    """Return a LIST of ModuleConfig dicts — a coordinated system for broad
    prompts, otherwise a single tool."""
    lower = prompt.lower()
    for keywords, builders in _SYSTEM_ROUTES:
        if any(_matches(k, lower) for k in keywords):
            return [_finalize(b()) for b in builders]  # type: ignore[operator]
    return [pick_template(prompt)]
