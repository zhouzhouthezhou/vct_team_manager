import json
import pandas as pd
import numpy as np
import random

class Team_Generator():
	def __init__(self):
		# (game-changers, vct-international, vct-challengers)
		self.LEAGUES = ['game-changers', 'vct-international', 'vct-challengers']

		# (2022, 2023, 2024)
		self.YEAR = 2024

		self.ROLES = ['duelist', 'sentinel', 'controller', 'initiator', 'flex']

		self.player_df = dict()
		self.pdf_dict = dict()
		self.agg_df = dict()

		for LEAGUE in self.LEAGUES:
			with open(f'{LEAGUE}/players.json', 'r', encoding='utf-8') as f:
				self.player_df[LEAGUE] = pd.DataFrame(json.load(f))
				
			with open(f'{LEAGUE}/{LEAGUE}-{self.YEAR}-pdfs.json', 'r', encoding='utf-8') as f:
				self.pdf_dict[LEAGUE] = json.load(f)

			self.agg_df[LEAGUE] = pd.read_pickle(f'{LEAGUE}/{LEAGUE}-{self.YEAR}-agg.pkl')
			self.agg_df[LEAGUE].drop(self.agg_df[LEAGUE].index[:1], inplace=True)
			self.agg_df[LEAGUE].reset_index(inplace=True)
			self.agg_df[LEAGUE] = self.agg_df[LEAGUE].sort_index(axis=1)

	def _sample_player(self, players_dict):
		players = list(players_dict.keys())
		probabilities = list(players_dict.values())
		return random.choices(players, weights=probabilities, k=1)[0]

	def _generate_random_team(self, role_groups):
		selected_team = {}
    
		for role, group in role_groups.items():
			player_pool = self.pdf_dict[group][role]
			selected_player = self._sample_player(player_pool)
			selected_team[role] = selected_player
    
		team_vector = dict()
		for k in selected_team.keys():
			id = selected_team[k]
			bucket = role_groups[k]
			name = self.player_df[bucket].loc[self.player_df[bucket]['id'] == id, ['handle']].drop_duplicates().head(1).values[0][0]
			team_vector[name] = self.agg_df[bucket].loc[self.agg_df[bucket]['id'] == id].drop(['id'], axis=1).round(3).values.flatten().tolist()

		return team_vector

	def generate_teams(self, n, role_groups):
		return [self._generate_random_team(role_groups) for _ in range(n)]