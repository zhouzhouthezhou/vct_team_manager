import json
import pandas as pd
import numpy as np
import random

class Team_Generator(self):
	def __init__():
		# (game-changers, vct-international, vct-challengers)
		self.LEAGUES = ['game-changers', 'vct-international', 'vct-challengers']

		# (2022, 2023, 2024)
		self.YEAR = 2024

		self.ROLES = ['duelist', 'sentinel', 'controller', 'initiator', 'flex']

		self.player_df = dict()
		self.pdf_dict = dict()
		self.agg_df = dict()

		for LEAGUE in LEAGUES:
    		with open(f'{LEAGUE}/players.json', 'r') as f:
        		player_df[LEAGUE] = pd.DataFrame(json.load(f))

    		with open(f'{LEAGUE}/{LEAGUE}-{YEAR}-pdfs.json', 'r') as f:
        		pdf_dict[LEAGUE] = json.load(f)

    		agg_df[LEAGUE] = pd.read_pickle(f'{LEAGUE}/{LEAGUE}-{YEAR}-agg.pkl')
    		agg_df[LEAGUE].drop(agg_df[LEAGUE].index[:1], inplace=True)
    		agg_df[LEAGUE].reset_index(inplace=True)
    		agg_df[LEAGUE] = agg_df[LEAGUE].sort_index(axis=1)

	def _sample_player(self, players_dict):
    	players = list(players_dict.keys())
    	probabilities = list(players_dict.values())
    	return random.choices(players, weights=probabilities, k=1)[0]

	def _generate_random_team(self, role_groups):
    	selected_team = {}
    
    	for role, group in role_groups.items():
        	player_pool = pdf_dict[group][role]
        	selected_player = self._sample_player(player_pool)
        	selected_team[role] = selected_player
    
    	team_vector = dict()
    	for k in selected_team.keys():
        	id = selected_team[k]
        	bucket = team_comp[k]
        	name = player_df[bucket].loc[player_df[bucket]['id'] == id, ['handle']].drop_duplicates().head(1).values[0][0]
        	team_vector[name] = agg_df[bucket].loc[agg_df[bucket]['id'] == id].drop(['id'], axis=1).values.flatten().tolist()

    	return team_vector

	def generate_teams(self, n, role_groups):
    	return [self._generate_random_team(role_groups) for _ in range(n)]