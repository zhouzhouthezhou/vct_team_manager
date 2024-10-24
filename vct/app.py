import json
import os
from services import bedrock_agent_runtime
import streamlit as st
import uuid
import re
import team_sampling
from botocore.exceptions import EventStreamError
import time
import random
import boto3
import logging

# Agent IDs and Agent Alias IDs to access LLMs
agent_id_A = st.secrets["agent_id_A"]
agent_alias_id_A = st.secrets["agent_alias_id_A"]
agent_id_T = st.secrets["agent_id_T"]
agent_alias_id_T = st.secrets["agent_alias_id_T"]
agent_id_TEAM = st.secrets["agent_id_TEAM"]
agent_alias_id_TEAM = st.secrets["agent_alias_id_TEAM"]
ui_title = 'VCT Team Manager'

# boto3 client to call bedrock agents
client = boto3.session.Session(region_name=st.secrets["AWS_DEFAULT_REGION"], aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"], aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"]).client(service_name="bedrock-agent-runtime")

# Logging config
logging.basicConfig(level=logging.INFO)

# Prompts and values needed for our LLM prompts
is_this_build_team_prompt = "Is this asking you to build a new VCT Valorant Team? Respond with only the word yes or no."
assign_roles_prompt = """ Respond to this with only a json object of the following format where the key is the player type and the value is the group. { "duelist": "vct-international", "sentinel": "vct-international", "controller": "vct-international", "initiator": "vct-international", "flex": "vct-international" }"""
team_prompt = "I am going to give you a list of python dictionaries. Each dictionary will have 5 key-value pairings representing the 5 players of a Valorant team. The key will represent the player's name. The value will be a python list that is a Yeo-Johnson normalized statistical break down of that player from the 2024 season. From the below teams, select only the best team and return the index in the list where the team dictionary resides. In your response, only include the integer for the index of the best team. Do not include any English words."
num_teams = 50
max_retries = 3

# Used to reset all of the various session fields
def init_state():
    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.session_id = None
    st.session_state.messages = []
    st.session_state.citations = []
    st.session_state.teams = []
    st.session_state.trace = {}

# Call the specified LLM agent
def call_llm(agent_id, agent_alias_id, session_id, prompt):
    retries = 0
    max_retries = 10
    while retries < max_retries:
        try:
            response = bedrock_agent_runtime.invoke_agent(
                client,
                agent_id,
                agent_alias_id,
                session_id,
                prompt
            )
            return response
        except EventStreamError as e:
            logging.info("Received throttling exception")
            retries += 1
            sleep_time = (2 ** retries) + random.uniform(0, 1)
            handle_throttle(round(sleep_time))
    
# Prints out to Front End messages for handling throttling exception
def handle_throttle(sleep_time):
    for seconds in range(sleep_time):
        placeholder.write(f"⏳ Throttling error, retrying in {sleep_time - seconds} seconds...")
        time.sleep(1)
    placeholder.write("Retrying...")

# General page configuration and initialization
st.set_page_config(page_title=ui_title, page_icon="https://cdn-icons-png.flaticon.com/512/4783/4783491.png", layout="wide")
st.title(ui_title)
if len(st.session_state.items()) == 0:
    init_state()

# Sidebar button to reset session state
with st.sidebar:
    if st.button("Reset Session"):
        init_state()

# Messages in the conversation
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"], unsafe_allow_html=True)

# Chat input that invokes the agent
if prompt := st.chat_input():
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("...")

        # First call to LLM A, asking if the request is asking to build a new VCT Team or not
        prompt_is_req_build_team = "\"" + prompt + "\" " + is_this_build_team_prompt

        llm_a_session_id = str(uuid.uuid4()) # We want this to be a new session every time
        response_build_new_team = call_llm(agent_id_A, agent_alias_id_A, llm_a_session_id, prompt_is_req_build_team)
        yes_or_no = response_build_new_team["output_text"]

        output_text = ""
        bedrock_agent_runtime.end_session(client, agent_id_A, agent_alias_id_A, llm_a_session_id)

        logging.info("1) LLM A output: " + yes_or_no)


        try:
            if "yes" in yes_or_no.lower():
                # Second call to LLM A is to determine which player type (duelist, sentinel, controller, initiator, flex) is going to be obtained from which VCT League (International, Challengers, Game Changers)
                # Reset LLM T to not have any context of any previous teams.
                if not st.session_state.session_id == None:
                    bedrock_agent_runtime.end_session(client, agent_id_TEAM, agent_alias_id_TEAM, st.session_state.session_id)
                st.session_state.session_id = str(uuid.uuid4())

                # Retry until we get a JSON object from LLM A
                retry = 0
                while "{" not in output_text and "}" not in output_text or retry >= max_retries:
                    llm_a_session_id = str(uuid.uuid4()) # We want this to be a new session every time
                    prompt_json = prompt + assign_roles_prompt

                    response_build_new_team = call_llm(agent_id_A, agent_alias_id_A, llm_a_session_id, prompt_json)
                    output_text = response_build_new_team["output_text"]
                    logging.info("2) LLM A output:" + output_text)
                    retry += 1
                
                bedrock_agent_runtime.end_session(client, agent_id_A, agent_alias_id_A, llm_a_session_id)

                # Remove everything before the { and after the }
                response_only_json = output_text = output_text[output_text.find("{"):output_text.rfind("}") + 1]
    
                # Call team_sampling to get the list of teams we need
                team_generator = team_sampling.Team_Generator()
                list_teams = team_generator.generate_teams(num_teams, json.loads(response_only_json))

                # First call to LLM T to determine which of the num_teams generated team is the best
                # Retry until we get a response with a proper index
                team_index = -1
                retry = 0
                while 0 <= team_index < len(num_teams) or retry >= max_retries:
                    build_team_prompt = team_prompt + "\n" + json.dumps(list_teams)
                    llm_t_session_id = str(uuid.uuid4()) # We want this to be a new session every time
                    response = call_llm(agent_id_T, agent_alias_id_T, llm_t_session_id, build_team_prompt)
                    bedrock_agent_runtime.end_session(client, agent_id_T, agent_alias_id_T, llm_t_session_id)
                    logging.info("3) LLM T output: " + response["output_text"])
                    try:
                        team_index = int(''.join(filter(str.isdigit, response["output_text"])))
                    except (ValueError, KeyError, TypeError) as e:
                        logging.info(f"Did not get a valid index from LLM T, retrying")
                    retry += 1

                # First call to LLM Team to analyze the selected team and give an explanation on why it would perform well
                team = list_teams[team_index]
                st.session_state.teams.append(team.keys()) # Add the player names to display in the side bar
                team_list_str = json.dumps(team)
                response = call_llm(agent_id_TEAM, agent_alias_id_TEAM, st.session_state.session_id, team_list_str)
                output_text = response["output_text"]
                logging.info("4) LLM TEAM output:" + output_text)  

                # Follow up call to LLM Team to prime it to be prepared to answer follow up questions on any of the players in the team chosen
                priming_prompt = "If you get asked to analyze of the players, use the statistics that I just sent. Explain initially that the statistics shown represent a a Yeo-Johnson normalized statistical break down from their VCT games."
                call_llm(agent_id_TEAM, agent_alias_id_TEAM, st.session_state.session_id, priming_prompt)

                logging.info("5) LLM TEAM priming call complete")  
            else:
                if st.session_state.session_id == None:
                    # If there is no session_id then a team has not been selected and the LLM cannot answer any VCT related questions without a team built
                    output_text = "Please ask to build a VCT Team before asking any other questions."
                    response = {"citations": [],"trace": []} 
                else:
                    # Call to LLM Team to ask follow up questions regarding a team that was build
                    response = call_llm(agent_id_TEAM, agent_alias_id_TEAM, st.session_state.session_id, prompt)

                    logging.info("6) LLM Team output: " +  response["output_text"])
                    output_text = response["output_text"]  
        except Exception as e:
            # Catching all exceptions and logging it to not break the user experience
            output_text = "An error has occurred. Please try again."
            logging.info(f"An error occurred: {e}")
            response = {"citations": [],"trace": []} 

        # Displaying all citations returned from LLM in the side bar
        if len(response["citations"]) > 0:
            citation_num = 1
            num_citation_chars = 0
            citation_locs = ""
            for citation in response["citations"]:
                end_span = citation["generatedResponsePart"]["textResponsePart"]["span"]["end"] + 1
                for retrieved_ref in citation["retrievedReferences"]:
                    citation_marker = f"[{citation_num}]"
                    output_text = output_text[:end_span + num_citation_chars] + citation_marker + output_text[end_span + num_citation_chars:]
                    citation_locs = citation_locs + "\n<br>" + citation_marker + " " + retrieved_ref["location"]["s3Location"]["uri"]
                    citation_num = citation_num + 1
                    num_citation_chars = num_citation_chars + len(citation_marker)
                output_text = output_text[:end_span + num_citation_chars] + "\n" + output_text[end_span + num_citation_chars:]
                num_citation_chars = num_citation_chars + 1
            output_text = output_text + "\n" + citation_locs

        placeholder.markdown(output_text, unsafe_allow_html=True)
        st.session_state.messages.append({"role": "assistant", "content": output_text})
        st.session_state.citations = response["citations"]
        st.session_state.trace = response["trace"]

trace_types_map = {
    "Pre-Processing": ["preGuardrailTrace", "preProcessingTrace"],
    "Orchestration": ["orchestrationTrace"],
    "Post-Processing": ["postProcessingTrace", "postGuardrailTrace"]
}

trace_info_types_map = {
    "preProcessingTrace": ["modelInvocationInput", "modelInvocationOutput"],
    "orchestrationTrace": ["invocationInput", "modelInvocationInput", "modelInvocationOutput", "observation", "rationale"],
    "postProcessingTrace": ["modelInvocationInput", "modelInvocationOutput", "observation"]
}

# Sidebar section for trace
with st.sidebar:
    # Displaying all generated teams and their members in the side bar
    st.title("Generated Teams")
    if len(st.session_state.teams) > 0:
        team_num = 1
        for team in st.session_state.teams:
            st.subheader("Team " + str(team_num))
            with st.expander(f"Team Members", expanded=False):
                st.markdown(', '.join(map(str, team)))
            team_num += 1


    st.title("Trace")

    # Show each trace types in separate sections
    step_num = 1
    for trace_type_header in trace_types_map:
        st.subheader(trace_type_header)

        # Organize traces by step similar to how it is shown in the Bedrock console
        has_trace = False
        for trace_type in trace_types_map[trace_type_header]:
            if trace_type in st.session_state.trace:
                has_trace = True
                trace_steps = {}

                for trace in st.session_state.trace[trace_type]:
                    # Each trace type and step may have different information for the end-to-end flow
                    if trace_type in trace_info_types_map:
                        trace_info_types = trace_info_types_map[trace_type]
                        for trace_info_type in trace_info_types:
                            if trace_info_type in trace:
                                trace_id = trace[trace_info_type]["traceId"]
                                if trace_id not in trace_steps:
                                    trace_steps[trace_id] = [trace]
                                else:
                                    trace_steps[trace_id].append(trace)
                                break
                    else:
                        trace_id = trace["traceId"]
                        trace_steps[trace_id] = [
                            {
                                trace_type: trace
                            }
                        ]

                # Show trace steps in JSON similar to the Bedrock console
                for trace_id in trace_steps.keys():
                    with st.expander(f"Trace Step " + str(step_num), expanded=False):
                        for trace in trace_steps[trace_id]:
                            trace_str = json.dumps(trace, indent=2)
                            st.code(trace_str, language="json", line_numbers=trace_str.count("\n"))
                    step_num = step_num + 1
        if not has_trace:
            st.text("None")

    st.subheader("Citations")
    if len(st.session_state.citations) > 0:
        citation_num = 1
        for citation in st.session_state.citations:
            for retrieved_ref_num, retrieved_ref in enumerate(citation["retrievedReferences"]):
                with st.expander("Citation [" + str(citation_num) + "]", expanded=False):
                    citation_str = json.dumps({
                        "generatedResponsePart": citation["generatedResponsePart"],
                        "retrievedReference": citation["retrievedReferences"][retrieved_ref_num]
                    }, indent=2)
                    st.code(citation_str, language="json", line_numbers=trace_str.count("\n"))
                citation_num = citation_num + 1
    else:
        st.text("None")