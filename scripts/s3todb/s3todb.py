import time
import logging
import requests
import boto3
import json

from collections import deque
from decimal import Decimal

import multiprocessing as mp

import pandas as pd

logging.basicConfig(
    format='{asctime} [{levelname}] {message}',
    style="{",
    datefmt="%H:%M",
    level=logging.INFO,
    force=True
)

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

def add_item_to_dynamodb(table_name, item):
    table = dynamodb.Table(table_name)
    response = table.put_item(Item=item)
    return response

def read_json_from_s3(bucket_name, file):
    response = s3.get_object(Bucket=bucket_name, Key=file)
    content = response['Body'].read().decode('utf-8')

    return json.loads(content)

def list_s3_files(bucket_name, prefix):
    response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)

    files = []
    if 'Contents' in response:
        for obj in response['Contents']:
            files.append(obj['Key'])

    return files

maps = {
    "Infinity": 'ABYSS',
    "Ascent": 'ASCENT',
    "Duality": 'BIND',
    "Foxtrot": 'BREEZE',
    "Canyon": 'FRACTURE',
    "Triad": 'HAVEN',
    "Port": 'ICEBOX',
    "Jam": 'LOTUS',
    "Pitt": 'PEARL',
    "Bonsai": 'SPLIT',
    "Juliett": 'SUNSET',
}

vec_fields = [
    'ROUND_NUMBER',
    'OUTCOME',
    'SIDE',
    'KILLS',
    'DEATHS',
    'ASSISTS',
    'COMBAT_SCORE',
    'KILLS_STINGER',
    'KILLS_BUCKY',
    'KILLS_JUDGE',
    'KILLS_SPECTRE',
    'KILLS_BULLDOG',
    'KILLS_GUARDIAN',
    'KILLS_PHANTOM',
    'KILLS_VANDAL',
    'KILLS_MARSHAL',
    'KILLS_OUTLAW',
    'KILLS_OPERATOR',
    'KILLS_ARES',
    'KILLS_ODIN',
    'KILLS_CLASSIC',
    'KILLS_SHORTY',
    'KILLS_FRENZY',
    'KILLS_GHOST',
    'KILLS_SHERIFF',
    'KILLS_MELEE',
    'TIME_ALIVE',
    'DEAD',
    'DAMAGE_TAKEN',
    'DAMAGE_DONE',
    'SPIKE_CARRY_PERCENT',
    'SPIKE_PLANT',
    'ASTRA_PICK_RATE',
    'BREACH_PICK_RATE',
    'BRIMSTONE_PICK_RATE',
    'CHAMBER_PICK_RATE',
    'CYPHER_PICK_RATE',
    'DEADLOCK_PICK_RATE',
    'FADE_PICK_RATE',
    'GEKKO_PICK_RATE',
    'HARBOR_PICK_RATE',
    'JETT_PICK_RATE',
    'KAYO_PICK_RATE',
    'KILLJOY_PICK_RATE',
    'NEON_PICK_RATE',
    'OMEN_PICK_RATE',
    'PHOENIX_PICK_RATE',
    'RAZE_PICK_RATE',
    'REYNA_PICK_RATE',
    'SAGE_PICK_RATE',
    'SKYE_PICK_RATE',
    'SOVA_PICK_RATE',
    'VIPER_PICK_RATE',
    'YORU_PICK_RATE',
    'ISO_PICK_RATE',
    'CLOVE_PICK_RATE',
    'VYSE_PICK_RATE',
    'DUELIST_PICK_RATE',
    'INITIATOR_PICK_RATE',
    'SENTINEL_PICK_RATE',
    'CONTROLLER_PICK_RATE',
    # TODO: map score
    # TODO: win type
]

class PlayerRound:
    def __init__(self, game_id, player_id, map):
        # TODO: add abilities, player killed data, more damage data
        self.metadata = {
            'game_id': game_id,
            'map': map,
        }
        self.vec = {'id': player_id}
        for v in vec_fields:
            self.vec[v] = 0

    def update_vec(self, idx, val):
        self.vec[idx] = val

    def add_vec(self, idx, i):
        self.vec[idx] += i

    def get_vec(self, idx):
        return self.vec[idx]

    def upload(self, ddb):
        for v in vec_fields:
            self.vec[v] = Decimal(str(self.vec[v]))
        self.vec['metadata'] = self.metadata
        add_item_to_dynamodb(ddb, self.vec)

class Game:
    def _process_event(self, event):
        if 'snapshot' in event:
            return

        # agent_name, agent_class, side, round number
        if 'roundStarted' in event:
            e = event['roundStarted']
            logging.debug(f'Round started {e}')

            self._processing_round = True
            self._curr_round_start_time = float(event['metadata']['eventTime']['omittingPauses'][:-1])

            attacking_team = str(e['spikeMode']['attackingTeam']['value'])
            # agent_name and agent_class
            for i, p in enumerate(self.player_loc.values()):
                pi = str(i+1)
                self.players[pi]['player_round'] = PlayerRound(self.game_id, p, self.map)

                agent = self.players[pi]['agent_name'] + '_PICK_RATE'
                agent_class = self.players[pi]['agent_role'] + '_PICK_RATE'

                self.players[pi]['player_round'].update_vec(agent, 1)
                self.players[pi]['player_round'].update_vec(agent_class, 1)

                # Set current round number
                self.players[pi]['player_round'].update_vec('ROUND_NUMBER', e['roundNumber'])

                # Set side
                if int(pi) in self.teams[attacking_team]['players']:
                    self.players[pi]['player_round'].update_vec('SIDE', 1)
                else:
                    self.players[pi]['player_round'].update_vec('SIDE', -1)

            return

        # Skip processing if not inside of a round
        if not self._processing_round:
            return

        cur_time = float(event['metadata']['eventTime']['omittingPauses'][:-1])

        # damage receive, damage dealt
        if 'damageEvent' in event:
            e = event['damageEvent']
            logging.debug(f'Damage Event {e}')

            # Set damage dealt
            if 'causerId' in e:
                causer = str(e['causerId']['value'])
                self.players[causer]['player_round'].add_vec('DAMAGE_DONE', e['damageAmount'])

            # Set damage received
            victim = str(e['victimId']['value'])
            self.players[victim]['player_round'].add_vec('DAMAGE_TAKEN', e['damageAmount'])

            return

        # death flag, weapon kill, time alive, kills, deaths, asissts,
        if 'playerDied' in event:
            e = event['playerDied']
            time_stamp = float(event['metadata']['eventTime']['omittingPauses'][:-1])
            logging.debug(f'Player Died {e}')

            # Set death flag and death counter
            dead_player = str(e['deceasedId']['value'])
            self.players[dead_player]['player_round'].update_vec('DEAD', 1)
            self.players[dead_player]['player_round'].add_vec('DEATHS', 1)

            # Set time alive
            time_alive = time_stamp - self._curr_round_start_time
            self.players[dead_player]['player_round'].update_vec('TIME_ALIVE', time_alive)

            # Update weapon kill tracker and kill counter
            killer = str(e['killerId']['value'])
            self.players[killer]['player_round'].add_vec('KILLS', 1)
            if 'weapon' in e:
                weapon_guid = e['weapon']['fallback']['guid']
                if weapon_guid == "":
                    self.players[killer]['player_round'].add_vec('KILLS_MELEE', 1)
                else:
                    g = requests.get(f'https://valorant-api.com/v1/weapons/{weapon_guid}')
                    wkey = 'KILLS_' + g.json()['data']['displayName'].upper()
                    self.players[killer]['player_round'].add_vec(wkey, 1)

            # Update assist counter
            if 'assistants' in e:
                for a in e['assistants']:
                    assister = str(a['assistantId']['value'])
                    self.players[assister]['player_round'].add_vec('ASSISTS', 1)
            return

        # spike plant, spike carry time, spike defuse
        if 'spikeStatus' in event:
            e = event['spikeStatus']
            logging.debug(f'Spike Status {e}')

            # Set spike plant flag and update spike carry time and spike defuse flag
            if e['status'] == "IN_HANDS" and 'carrier' in e:
                if not 'carrier' in e:
                    logging.warning("SPIKE IN_HANDS event with no carrier found")
                else:
                    self._curr_spike_carrier = str(e['carrier']['value'])
                self._curr_spike_pickup_stamp = float(event['metadata']['eventTime']['omittingPauses'][:-1])
            elif e['status'] == "PLANTED":
                self.players[self._curr_spike_carrier]['player_round'].update_vec('SPIKE_PLANT', 1)
                self.players[self._curr_spike_carrier]['player_round'].add_vec('SPIKE_CARRY_PERCENT', cur_time - self._curr_spike_pickup_stamp)
            elif e['status'] == "ON_GROUND":
                self.players[self._curr_spike_carrier]['player_round'].add_vec('SPIKE_CARRY_PERCENT', cur_time - self._curr_spike_pickup_stamp)

            return

        # combat score, outcome, time alive, noramlize spike carry time
        if 'roundDecided' in event:
            e = event['roundDecided']
            logging.debug(f'Round Decided {e}')

            round_length = cur_time - self._curr_round_start_time
            winning_team = str(e['result']['winningTeam']['value'])
            for p in self.players:
                # Set outcome
                if int(p) in self.teams[winning_team]['players']:
                    self.players[p]['player_round'].update_vec('OUTCOME', 1)
                else:
                    self.players[p]['player_round'].update_vec('OUTCOME', -1)

                # Set time alive
                if self.players[p]['player_round'].get_vec('DEAD') == 0:
                    self.players[p]['player_round'].add_vec('TIME_ALIVE', round_length)

                # Normalize spike time
                spike_time = self.players[p]['player_round'].get_vec('SPIKE_CARRY_PERCENT')
                self.players[p]['player_round'].update_vec('SPIKE_CARRY_PERCENT', spike_time / round_length)


            round_end_stamp = float(event['metadata']['eventTime']['omittingPauses'][:-1])
            while 'snapshot' not in event:
                event = self.event_feed.popleft()

            e = event['snapshot']

            # Set combat score
            for p in e['players']:
                player = str(p['playerId']['value'])
                self.players[player]['player_round'].update_vec('COMBAT_SCORE', p['scores']['combatScore']['roundScore'])

            self._processing_round = False
            self._curr_round_start_time = None
            self._curr_spike_carrier = None
            self._curr_spike_pickup_stamp = None
            self._curr_round_start_time = None

            for p in self.players.values():
                p['player_round'].upload(self.ddb)

            return


    def __init__(self, struct):
        file = struct['file']

        self.ddb = struct['ddb']
        self.mapping_df = struct['mapping']
        self.team_df = struct['team']

        self.name = file.split('/')[-1]
        self.players = dict()
        self.teams = dict()
        self._curr_round_start_time = None
        self._curr_spike_carrier = None
        self._curr_spike_pickup_stamp = None
        self._curr_round_start_time = None
        self._processing_round = False

        logging.warning(f"Ingesting {self.name}")
        j = read_json_from_s3(bucket, file)

        self.event_feed = deque(j)

        first_event = self.event_feed.popleft()

        self.game_id = first_event['platformGameId']

        self.player_loc = self.mapping_df.loc[self.mapping_df['platformGameId'] == self.game_id, 'participantMapping'].values[0]

        second_event = self.event_feed.popleft()

        for i, p in enumerate(self.player_loc.values()):
            self.players[str(i+1)] = {
                'player_round': None,
                'agent_name': "",
                'agent_role': "",
            }

        self.map = maps[second_event['configuration']['selectedMap']['fallback']['displayName']]

        self.player_agents = dict()
        for i, p in enumerate(second_event['configuration']['players']):
            agent_guid = p['selectedAgent']['fallback']['guid']
            agent_data = requests.get(f'https://valorant-api.com/v1/agents/{agent_guid}')
            self.players[str(p['playerId']['value'])]['agent_name'] = agent_data.json()['data']['displayName'].upper()
            self.players[str(p['playerId']['value'])]['agent_role'] = agent_data.json()['data']['role']['displayName'].upper()

        teamid = str(second_event['configuration']['teams'][0]['teamId']['value'])
        self.teams[teamid] = dict()
        self.teams[teamid]['players'] = [p['value'] for p in second_event['configuration']['teams'][0]['playersInTeam']]
        self.teams[teamid]['name'] = self.team_df.iloc[second_event['configuration']['teams'][0]['teamId']['value']]['slug']

        teamid = str(second_event['configuration']['teams'][1]['teamId']['value'])
        self.teams[teamid] = dict()
        self.teams[teamid]['players'] = [p['value'] for p in second_event['configuration']['teams'][1]['playersInTeam']]
        self.teams[teamid]['name'] = self.team_df.iloc[second_event['configuration']['teams'][1]['teamId']['value']]['slug']

        # ingest events
        logging.info(f"Ingesting events for {self.name}")
        while len(self.event_feed) != 0:
            current_event = self.event_feed.popleft()
            self._process_event(current_event)
        logging.info(f"Done ingesting events for {self.name}")

# (game-changers, vct-international, vct-challengers)
leagues = {
    #'game-changers': 'RoundVec-Change',
    'vct-international': 'RoundVec-VctInt',
}

# (2022, 2023, 2024)
years = [2022, 2023, 2024]


bucket = "actualvctdata"
def consume_game(g):
    Game(g)

if __name__ == '__main__':
    for LEAGUE, ddb in leagues.items():
        for YEAR in years:
            player_df = pd.DataFrame(read_json_from_s3(bucket, f'{LEAGUE}/esports-data/players.json'))
            mapping_df = pd.DataFrame(read_json_from_s3(bucket, f'{LEAGUE}/esports-data/mapping_data.json'))
            team_df = pd.DataFrame(read_json_from_s3(bucket, f'{LEAGUE}/esports-data/teams.json'))
            tournament_df = pd.DataFrame(read_json_from_s3(bucket, f'{LEAGUE}/esports-data/tournaments.json'))
            league_df = pd.DataFrame(read_json_from_s3(bucket, f'{LEAGUE}/esports-data/leagues.json'))

            s3_game_files = list_s3_files(bucket, f'{LEAGUE}/games/{YEAR}')
            game_files = list()
            for f in s3_game_files:
                game_files.append({
                    'file': f,
                    'ddb': ddb,
                    'mapping': mapping_df,
                    'team': team_df
                    })

            start = time.time()

            print(f'found {mp.cpu_count()} cores')

            num_processes = mp.cpu_count() * 1
            with mp.Pool(processes=num_processes) as pool:
                pool.map(consume_game, game_files)

            delta = time.time() - start
            print(f'parallel ingestion took {delta:0.2f} seconds')
