import streamlit as st
import json
from learner import MasteryTracker
import llm

# Initialize Streamlit Page Config
st.set_page_config(page_title="AI Learning Assistant", page_icon="🎓", layout="wide")

# Initialize the Mastery Tracker backend in session state
if "tracker" not in st.session_state:
    st.session_state.tracker = MasteryTracker()
tracker = st.session_state.tracker

# ==========================================
# SIDEBAR NAVIGATION & LIVE DASHBOARD
# ==========================================
st.sidebar.title("Navigation")
choice = st.sidebar.radio("Go to", ["Learn Mode", "Diagnostic Quiz"])
st.sidebar.markdown("---")
st.sidebar.subheader("📊 Live Mastery Status")

profile_data = tracker.get_profile()
sorted_topics = profile_data[0] if len(profile_data) > 0 else []
mastery_dict = profile_data[1] if len(profile_data) > 1 else {}

if sorted_topics:
    for topic in sorted_topics:
        score = mastery_dict.get(topic, 0.2)
        st.sidebar.metric(label=topic, value=f"{int(score * 100)}%")
else:
    st.sidebar.info("No topics tracked yet. Start learning!")


# ==========================================
# TAB 1: LEARN MODE
# ==========================================
if choice == "Learn Mode":
    st.title("🎓 Interactive Tutor")
    st.markdown("Chat history is maintained per topic and resets automatically when you switch topics.")

    if sorted_topics:
        st.markdown("### ⚠️ Focus Areas (Your Weakest Topics)")
        cols = st.columns(min(3, len(sorted_topics)))
        for i, topic in enumerate(sorted_topics[:3]):
            with cols[i]:
                score = mastery_dict.get(topic, 0.2)
                st.metric(label=topic, value=f"{int(score * 100)}%", delta="Needs Practice", delta_color="inverse")
        st.markdown("---")

    if "active_topic" not in st.session_state:
        st.session_state.active_topic = ""
    if "learn_history" not in st.session_state:
        st.session_state.learn_history = []
    if "learn_step" not in st.session_state:
        st.session_state.learn_step = "input"
    if "current_data" not in st.session_state:
        st.session_state.current_data = None

    # Search bar
    topic_input = st.text_input("What concept would you like to learn?", value=st.session_state.active_topic)

    # 1. Manual Start Button
    if st.button("Start Learning"):
        target = topic_input.strip()
        if target:
            if target != st.session_state.active_topic:
                st.session_state.active_topic = target
                st.session_state.learn_history = []
            st.session_state.current_data = None
            st.session_state.learn_step = "generating"
            st.rerun()
        else:
            st.warning("Please enter a valid topic.")

    # 2. Automated Generation Engine (Handles both manual start and deep dive clicks)
    if st.session_state.learn_step == "generating":
        target_topic = st.session_state.active_topic
        with st.spinner(f"Retrieving documents and explaining {target_topic}..."):
            try:
                reply = llm.learn(target_topic, st.session_state.learn_history, llm.URL_FLASH)
                
                if "doesnt exist" in reply:
                    st.warning(reply)
                    st.session_state.learn_step = "input"
                else:
                    response_data = json.loads(reply)
                    st.session_state.current_data = response_data
                    
                    # Append chat history
                    st.session_state.learn_history.append({"role": "user", "parts": [{"text": target_topic}]})
                    st.session_state.learn_history.append({"role": "model", "parts": [{"text": reply}]})
                    
                    st.session_state.learn_step = "explaining"
                    st.rerun()
            except Exception as e:
                st.error(f"Generation Error: {e}")
                st.session_state.learn_step = "input"

    # 3. Learning Flow (Explaining -> Questioning -> Graded)
    if st.session_state.learn_step in ["explaining", "questioning", "graded"] and st.session_state.current_data:
        data = st.session_state.current_data
        
        st.subheader(f"Topic: {st.session_state.active_topic}")
        st.markdown(data.get("explanation", ""))
        st.markdown("---")

        if st.session_state.learn_step == "explaining":
            if st.button("Next: Check Understanding"):
                st.session_state.learn_step = "questioning"
                st.rerun()

        if st.session_state.learn_step in ["questioning", "graded"]:
            q_data = data.get("check_question", {})
            q_text = q_data.get("question_text", "Explain what you just learned.")
            ideal_ans = q_data.get("ideal_answer", "N/A")
            weight = q_data.get("weightage", 1)
            
            st.markdown(f"### 📝 Check Question (Weightage: {weight} Marks)")
            st.info(q_text)
            student_answer = st.text_area("Your Answer:", key="student_open_ans")

            if st.session_state.learn_step == "questioning":
                if st.button("Submit Answer"):
                    if student_answer.strip():
                        with st.spinner("Grading..."):
                            try:
                                submission = [[q_text, student_answer, 1, weight, st.session_state.active_topic, ideal_ans]]
                                grade_results = llm.grade(submission)
                                marks, feedback = grade_results[0][0], grade_results[0][1]
                            except Exception as e:
                                st.error(f"Grading Error: {e}")
                                marks, feedback = 0, "Error during grading."
                        
                        tracker.update_mastery(
                            topic=st.session_state.active_topic,
                            weightage=weight,
                            marks_earned=marks,
                            type=1
                        )
                        
                        st.session_state.graded_marks = marks
                        st.session_state.graded_feedback = feedback
                        st.session_state.learn_step = "graded"
                        st.rerun()
                    else:
                        st.warning("Please write an answer before submitting.")

            if st.session_state.learn_step == "graded":
                marks = st.session_state.graded_marks
                
                if marks == weight:
                    st.success(f"**Correct! ({marks}/{weight} Marks)**")
                    st.balloons()
                elif marks > 0:
                    st.warning(f"**Partial Credit ({marks}/{weight} Marks)**")
                else:
                    st.error(f"**Incorrect (0/{weight} Marks)**")

                st.markdown(f"**Reference Solution:** {ideal_ans}")
                st.info(f"**Grader Feedback:** {st.session_state.graded_feedback}")
                st.markdown("---")

                # --- DEEP DIVE BUTTONS (Preserves History & Auto-Generates) ---
                deep_dives = data.get("deep_dive_topics", [])
                if deep_dives:
                    st.markdown("### 🔍 Want to go deeper? Choose a sub-topic:")
                    cols = st.columns(len(deep_dives))
                    
                    for i, sub_topic in enumerate(deep_dives):
                        button_key = f"deep_dive_{i}_{st.session_state.active_topic}"
                        
                        if cols[i].button(sub_topic, key=button_key):
                            st.session_state.active_topic = sub_topic
                            # Chat history is intentionally preserved here!
                            st.session_state.current_data = None
                            st.session_state.learn_step = "generating" # Instantly triggers generation
                            st.rerun()
                            
                st.markdown("---")

                if st.button("Learn Another Topic"):
                    st.session_state.active_topic = ""
                    st.session_state.learn_history = []
                    st.session_state.current_data = None
                    st.session_state.learn_step = "input"
                    st.rerun()


# ==========================================
# TAB 2: QUIZ MODE (Adaptive Material Assessment)
# ==========================================
elif choice == "Diagnostic Quiz":
    st.title("🎯 Adaptive Assessment")
    
    available_materials = llm.get_available_materials()
    
    if not available_materials:
        st.warning("No study materials found in the database. Please process documents first.")
        st.stop()

    if "quiz_questions" not in st.session_state:
        st.session_state.quiz_questions = []
    if "quiz_current_index" not in st.session_state:
        st.session_state.quiz_current_index = 0
    if "quiz_student_answers" not in st.session_state:
        st.session_state.quiz_student_answers = []
    if "quiz_final_grades" not in st.session_state:
        st.session_state.quiz_final_grades = []

    st.markdown("### 1. Select Study Scope")
    selected_materials = st.multiselect("Choose lectures, videos, or chapters to test yourself on:", available_materials)

    if not st.session_state.quiz_questions:
        if st.button("Generate Adaptive Quiz"):
            if not selected_materials:
                st.warning("Please select at least one study material.")
            else:
                with st.spinner("Analyzing your mastery profile and generating targeted questions..."):
                    try:
                        questions = llm.quiz(selected_materials, mastery_profile=mastery_dict)
                        if questions:
                            st.session_state.quiz_questions = questions
                            st.session_state.quiz_current_index = 0
                            st.session_state.quiz_student_answers = []
                            st.session_state.quiz_final_grades = []
                            st.rerun()
                        else:
                            st.error("Failed to generate questions. Try again.")
                    except Exception as e:
                        st.error(f"Error: {e}")
                        
    elif st.session_state.quiz_current_index < len(st.session_state.quiz_questions):
        idx = st.session_state.quiz_current_index
        total_q = len(st.session_state.quiz_questions)
        q = st.session_state.quiz_questions[idx]
        
        q_text = q[0]
        q_type = q[1]
        q_weight = q[2]
        q_topic = q[3]
        q_options = q[4]
        
        st.markdown(f"**Question {idx + 1} of {total_q}** | Targeted Topic: `{q_topic}` | Weightage: `{q_weight}`")
        st.markdown(f"### {q_text}")
        
        with st.form(key=f"q_form_{idx}"):
            if q_type == 0 and q_options:
                student_ans = st.radio("Select your answer:", q_options)
            else:
                student_ans = st.text_area("Write your answer:")
                
            submit = st.form_submit_button("Next Question" if idx < total_q - 1 else "Finish & Grade Quiz")
            
            if submit:
                if not student_ans or not student_ans.strip():
                    st.warning("Please provide an answer.")
                else:
                    st.session_state.quiz_student_answers.append(student_ans)
                    st.session_state.quiz_current_index += 1
                    st.rerun()

    elif st.session_state.quiz_current_index == len(st.session_state.quiz_questions) and not st.session_state.quiz_final_grades:
        with st.spinner("Grading your entire quiz and updating mastery models..."):
            submission_batch = []
            for i, q in enumerate(st.session_state.quiz_questions):
                q_text = q[0]
                q_type = q[1]
                q_weight = q[2]
                q_topic = q[3]
                q_correct = q[5]
                
                student_ans = st.session_state.quiz_student_answers[i]
                submission_batch.append([q_text, student_ans, q_type, q_weight, q_topic, q_correct])
            
            try:
                grades = llm.grade(submission_batch)
                st.session_state.quiz_final_grades = grades
                
                for i, res in enumerate(grades):
                    marks = res[0]
                    q_topic = submission_batch[i][4]
                    q_weight = submission_batch[i][3]
                    q_type = submission_batch[i][2]
                    
                    tracker.update_mastery(
                        topic=q_topic,
                        weightage=q_weight,
                        marks_earned=marks,
                        type=q_type
                    )
                st.rerun()
            except Exception as e:
                st.error(f"Error during batch grading: {e}")

    elif st.session_state.quiz_final_grades:
        st.success("Quiz Complete!")
        
        total_earned = 0
        total_possible = 0
        weak_topics = set()
        
        st.markdown("### Post-Assessment Report")
        
        for i, q in enumerate(st.session_state.quiz_questions):
            q_text = q[0]
            q_type = q[1]
            q_weight = q[2]
            q_topic = q[3]
            q_correct = q[5]
            q_explanation = q[6] if len(q) > 6 else "No explanation generated."
            
            student_ans = st.session_state.quiz_student_answers[i]
            marks_earned, feedback = st.session_state.quiz_final_grades[i]
            
            total_earned += marks_earned
            total_possible += q_weight
            
            if marks_earned < q_weight:
                weak_topics.add(q_topic)
            
            with st.expander(f"Q{i+1} [{q_topic}]: {q_text} ({marks_earned}/{q_weight} Marks)"):
                st.markdown(f"**Your Answer:** {student_ans}")
                st.markdown(f"**Reference Solution:** {q_correct}")
                st.markdown(f"**Explanation:** {q_explanation}")
                st.info(f"**Grader Feedback:** {feedback}")
                
        st.markdown("---")
        st.metric("Total Score", f"{total_earned} / {total_possible}")
        
        if weak_topics:
            st.warning(f"**Identified Weaknesses:** You lost marks in the following areas: `{', '.join(weak_topics)}`. We recommend returning to Learn Mode to review these concepts.")
        else:
            st.success("Excellent work! No significant weaknesses identified in this material scope.")
        
        if st.button("Start a New Quiz"):
            st.session_state.quiz_questions = []
            st.session_state.quiz_current_index = 0
            st.session_state.quiz_student_answers = []
            st.session_state.quiz_final_grades = []
            st.rerun()