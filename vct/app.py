import json
from services import bedrock_agent_runtime
import streamlit as st
import uuid
import team_sampling
import team_assignment
from botocore.exceptions import EventStreamError
import time
import random
import boto3
import logging
from pathlib import Path

image_dir = Path(__file__).parent / "images"
print(str(image_dir))

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
logging.basicConfig(level=logging.CRITICAL)

# Prompts and values needed for our LLM prompts
is_this_build_team_prompt = "Is this asking you to build a new VCT Valorant Team? Respond with only the word yes or no."
is_this_multi_region_prompt = "Is this asking you to build a team with players from more than two different regions? If they do not specify, default to no. Respond with only the word yes or no."
assign_roles_prompt = """ Respond to this with only a json object of the following format where the key is the player type and the value is the group. { "duelist": "vct-international", "sentinel": "vct-international", "controller": "vct-international", "initiator": "vct-international", "flex": "vct-international" }"""
team_prompt = "I am going to give you a list of python dictionaries. Each dictionary will have 5 key-value pairings representing the 5 players of a Valorant team. The key will represent the player's name. The value will be a python list that is a Yeo-Johnson normalized statistical break down of that player from the 2024 season. From the below teams, select only the best team and return the index in the list where the team dictionary resides. In your response, only include the integer for the index of the best team. Do not include any English words."
subs_prompt_first = "Send the index of the second best team that does not share any players with the team at index "
subs_prompt_second = ". Do not send any english words. Only send the index of the second best team. Do not send the same index as the first best team"
is_this_followup_prompt = "Is this prompt asking a follow-up question to a valorant team? Follow up questions may include but are not limited to asking for what recent performances or statistics justify the inclusion of a player in the team, if a player is unavailable, who would be a suitable replacement and why, which maps would this team composition excel in and why, what player would take a leadership (IGL) role and why, and any role-specific (duelists, sentinels, controllers, initiators) metrics and justifications (how effective is a player in initiating fights and security entry kills). Respond with only the word yes or no"
priming_prompt = "If you get asked what recent performances or statistics justify the inclusion of a certain player, which maps this team composition would excel in, which player would take a leadership (IGL) role, or any role specific metrics and justifications (duelists, sentinels, controllers, initiators), use the statistics that I initially sent in addition to the team that you generated. Explain first that the statistics shown represent a a Yeo-Johnson normalized statistical break down from their VCT games. Compare the statistics of the asked player to others using metrics such as standard deviation. Do you return the exact normalized statistics for the player. If you get asked if a player were unavailable, who would be a suitable replacement and why, select a proper player in the following team. The team will be a python dictionary like the one I sent previously. The dictionary will have 5 key-value pairings representing the 5 players of a Valorant team. The key represents the player name. The value is a python tuple. The first value in the list is a Yeo-Johnson normalized statistical break down of that player. Do not select a player as a suitable replacement as the player who is unavailable. Ensure that they names of the two players are unique."
num_teams = 50
max_retries = 3

# Used to reset all the various session fields
def init_state():
    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.session_id = None
    st.session_state.messages = []
    st.session_state.teams = []
    st.session_state.subs_list = []
    st.session_state.first_question = True

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

    with (st.chat_message("assistant")):
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
                # Second call to LLM A, asking if the request is asking if this is asking for a multi-region team or not
                prompt_multiple_regions = "\"" + prompt + "\" " + is_this_multi_region_prompt

                llm_a_session_id = str(uuid.uuid4()) # We want this to be a new session every time
                response_multiple_regions = call_llm(agent_id_A, agent_alias_id_A, llm_a_session_id, prompt_multiple_regions)
                yes_or_no_regions = response_multiple_regions["output_text"]
                more_than_two_regions = "yes" in yes_or_no_regions.lower()

                bedrock_agent_runtime.end_session(client, agent_id_A, agent_alias_id_A, llm_a_session_id)

                # Third call to LLM A is to determine which player type (duelist, sentinel, controller, initiator, flex) is going to be obtained from which VCT League (International, Challengers, Game Changers)
                # Reset LLM T to not have any context of any previous teams.
                if not st.session_state.session_id == None:
                    bedrock_agent_runtime.end_session(client, agent_id_TEAM, agent_alias_id_TEAM, st.session_state.session_id)
                st.session_state.session_id = str(uuid.uuid4())
                st.session_state.subs_list = []
                st.session_state.first_question = True

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
                response_only_json = json.loads(output_text[output_text.find("{"):output_text.rfind("}") + 1])

                # Call team_sampling to get the list of teams we need
                team_generator = team_sampling.Team_Generator()

                # Add the regions list
                regions_list = team_assignment.assign_regions(response_only_json, more_than_two_regions)
                response_only_json["region"] = regions_list

                list_teams = team_generator.generate_teams(num_teams, response_only_json)

                # First call to LLM T to determine which of the num_teams generated team is the best
                # Retry until we get a response with a proper index
                team_index = None
                retry = 0
                llm_t_session_id = ""
                while (team_index is None or (team_index is not None and (team_index < 0 or team_index >= num_teams)) and retry <= max_retries):
                    build_team_prompt = team_prompt + "\n" + json.dumps(list_teams)
                    llm_t_session_id = str(uuid.uuid4()) # We want this to be a new session every time
                    response = call_llm(agent_id_T, agent_alias_id_T, llm_t_session_id, build_team_prompt)
                    logging.info("3) LLM T output: " + response["output_text"])
                    try:
                        team_index = int(''.join(filter(str.isdigit, response["output_text"])))
                    except (ValueError, KeyError, TypeError) as e:
                        logging.info(f"Did not get a valid index from LLM T, retrying")
                    retry += 1

                # Retry until we get a response with a proper index
                subs_index = None
                retry = 0
                while (subs_index is None or (subs_index is not None and (subs_index < 0 or subs_index >= num_teams)) and retry <= max_retries):
                    build_subs_prompt = subs_prompt_first + str(team_index) + subs_prompt_second + "\n" + json.dumps(list_teams)
                    response = call_llm(agent_id_T, agent_alias_id_T, llm_t_session_id, build_subs_prompt)
                    logging.info("3.5) LLM T output: " + response["output_text"])
                    try:
                        subs_index = int(''.join(filter(str.isdigit, response["output_text"])))
                    except (ValueError, KeyError, TypeError) as e:
                        logging.info(f"Did not get a valid index from LLM T, retrying")
                    retry += 1

                bedrock_agent_runtime.end_session(client, agent_id_T, agent_alias_id_T, llm_t_session_id)
                subs = list_teams[subs_index]
                st.session_state.subs_list = json.dumps(subs)

                # First call to LLM Team to analyze the selected team and give an explanation on why it would perform well
                team = list_teams[team_index]
                st.session_state.teams.append(team.keys()) # Add the player names to display in the side bar
                team_list_str = json.dumps(team)
                response = call_llm(agent_id_TEAM, agent_alias_id_TEAM, st.session_state.session_id, team_list_str)
                output_text = response["output_text"]
                logging.info("4) LLM TEAM output:" + output_text)
            else:
                if st.session_state.session_id == None:
                    # If there is no session_id then a team has not been selected and the LLM cannot answer any VCT related questions without a team built
                    output_text = "Please ask to build a VCT Team before asking any other questions."
                else:
                    # Call to LLM A, asking if the request is a valid follow up question or not
                    prompt_is_follow_up = "\"" + prompt + "\" " + is_this_followup_prompt

                    llm_a_session_id = str(uuid.uuid4()) # We want this to be a new session every time
                    response_build_new_team = call_llm(agent_id_A, agent_alias_id_A, llm_a_session_id, prompt_is_follow_up)
                    yes_or_no = response_build_new_team["output_text"]

                    output_text = ""
                    bedrock_agent_runtime.end_session(client, agent_id_A, agent_alias_id_A, llm_a_session_id)

                    logging.info("1) LLM A output: " + yes_or_no)
                    if "yes" in yes_or_no.lower():
                        if st.session_state.first_question:
                            # Follow up call to LLM Team to prime it to be prepared to answer follow up questions on any of the players in the team chosen
                            priming_prompt_with_subs = priming_prompt + "\n" + st.session_state.subs_list
                            logging.info("Priming call: ", priming_prompt_with_subs)
                            call_llm(agent_id_TEAM, agent_alias_id_TEAM, st.session_state.session_id, priming_prompt)
                            logging.info("5) LLM TEAM priming call complete")

                        # Call to LLM Team to ask follow up questions regarding a team that was build
                        response = call_llm(agent_id_TEAM, agent_alias_id_TEAM, st.session_state.session_id, prompt)

                        logging.info("6) LLM Team output: " +  response["output_text"])
                        output_text = response["output_text"]
                        st.session_state.first_question = False
                    else:
                        # If this is not a follow up question on a team the LLM cannot answer
                        output_text = "Please only ask questions regarding a VCT Team that was previously built."
        except Exception as e:
            # Catching all exceptions and logging it to not break the user experience
            output_text = "An error has occurred. Please try again."
            logging.info(f"An error occurred: {e}")

        placeholder.markdown(output_text, unsafe_allow_html=True)
        st.session_state.messages.append({"role": "assistant", "content": output_text})


role_images = ['duelist-valorant.png','sentinel-valorant.png','initiator-valorant.png','controller-valorant.png','flex-valorant.png',]
# Sidebar section for trace
with st.sidebar:
    # Displaying all generated teams and their members in the side bar
    st.title("Generated Teams")
    if len(st.session_state.teams) > 0:
        team_num = 1
        for team in st.session_state.teams:
            st.subheader("Team " + str(team_num))
            with st.expander(f"Team Members", expanded=False):
                for i in range(len(role_images)):
                    col1, col2 = st.columns([1, 6])  # [1, 4] sets the relative widths of the columns
                    with col1:
                        ipath = str(image_dir / role_images[i])
                        st.image(ipath, width=25)
                    with col2:
                        st.markdown(team[i])
            team_num += 1
