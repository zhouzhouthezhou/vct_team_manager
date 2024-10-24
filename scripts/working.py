class PlayerRound:
    def __init__(self, game_id, player_id, map):
        # TODO: add abilities, player killed data, more damage data
        self.game_id = game_id
        self.player_id = player_id
        self.map = map
        self.vec = [0] * len(RoundVec)

    def update_vec(self, idx, val):
        self.vec[idx] = val

    def add_vec(self, idx, i):
        self.vec[idx] += i

    def get_vec(self, idx):
        return self.vec[idx]

class PlayerGame:
    def __init__(self, p):
        self.player_id = p
        self.rounds = list()
        self.vec = None

    def new_round(self, game_id, player_id, map):
        self.rounds.append(PlayerRound(game_id, player_id, map))

    def update_current_round(self, idx, val):
        self.rounds[-1].update_vec(idx, val)

    def add_current_round(self, idx, i):
        self.rounds[-1].add_vec(idx, i)

    def get_current_round_val(self, idx):
        return self.rounds[-1].get_vec(idx)

    def calculate_game_vec(self):
        round_vecs = map(lambda x: x.vec, self.rounds)
        game_vec = map(lambda x: x/float(len(self.rounds)), map(sum, zip(*round_vecs)))
        self.vec = list(game_vec)
        self.vec[RoundVec.ROUND_NUMBER.value] = max([r.vec[RoundVec.ROUND_NUMBER.value] for r in self.rounds])

        if self.player_id not in player_bank:
            player_bank[self.player_id] = Player(self.player_id)
        player_bank[self.player_id].add_game(self)

class Player:
    def __init__(self, p):
        self.player_id = p
        self.games = list()
        self.vec = None

    def add_game(self, game):
        self.games.append(game)

    def calculate_player_vec(self):
        game_vecs = map(lambda x: x.vec, self.games)
        player_vec = map(lambda x: x/float(len(self.games)), map(sum, zip(*game_vecs)))
        self.vec = list(player_vec)

class Game:
    def _process_event(self, event):
        if 'snapshot' in event:
            return

        # side, round number
        if 'roundStarted' in event:
            e = event['roundStarted']
            logging.debug(f'Round started {e}')

            self._processing_round = True
            self._curr_round_start_time = float(event['metadata']['eventTime']['omittingPauses'][:-1])
            attacking_team = str(e['spikeMode']['attackingTeam']['value'])
            for p in self.players:
                self.players[p].new_round(self.game_id, p, self.map)
                # Set current round number
                self.players[p].update_current_round(RoundVec.ROUND_NUMBER.value, e['roundNumber'])

                # Set side
                if int(p) in self.teams[attacking_team]['players']:
                    self.players[p].update_current_round(RoundVec.SIDE.value, 1)
                else:
                    self.players[p].update_current_round(RoundVec.SIDE.value, -1)
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
                self.players[causer].add_current_round(RoundVec.DAMAGE_DONE.value, e['damageAmount'])

            # Set damage received
            victim = str(e['victimId']['value'])
            self.players[victim].add_current_round(RoundVec.DAMAGE_TAKEN.value, e['damageAmount'])

            return

        # death flag, weapon kill, time alive, kills, deaths, asissts,
        if 'playerDied' in event:
            e = event['playerDied']
            time_stamp = float(event['metadata']['eventTime']['omittingPauses'][:-1])
            logging.debug(f'Player Died {e}')

            # Set death flag and death counter
            dead_player = str(e['deceasedId']['value'])
            self.players[dead_player].update_current_round(RoundVec.DEAD.value, 1)
            self.players[dead_player].add_current_round(RoundVec.DEATHS.value, 1)

            # Set time alive
            time_alive = time_stamp - self._curr_round_start_time
            self.players[dead_player].update_current_round(RoundVec.TIME_ALIVE.value, time_alive)

            # Update weapon kill tracker and kill counter
            killer = str(e['killerId']['value'])
            self.players[killer].add_current_round(RoundVec.KILLS.value, 1)
            if 'weapon' in e:
                weapon_guid = e['weapon']['fallback']['guid']
                if weapon_guid == "":
                    self.players[killer].add_current_round(Weapon.MELEE.value, 1)
                else:
                    g = requests.get(f'https://valorant-api.com/v1/weapons/{weapon_guid}')
                    Weapon[g.json()['data']['displayName'].upper()]
                    self.players[killer].add_current_round(Weapon[g.json()['data']['displayName'].upper()].value, 1)

            # Update assist counter
            if 'assistants' in e:
                for a in e['assistants']:
                    assister = str(a['assistantId']['value'])
                    self.players[assister].add_current_round(RoundVec.ASSISTS.value, 1)
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
                self.players[self._curr_spike_carrier].update_current_round(RoundVec.SPIKE_PLANT.value, 1)
                self.players[self._curr_spike_carrier].add_current_round(RoundVec.SPIKE_CARRY_PERCENT.value, cur_time - self._curr_spike_pickup_stamp)
            elif e['status'] == "ON_GROUND":
                self.players[self._curr_spike_carrier].add_current_round(RoundVec.SPIKE_CARRY_PERCENT.value, cur_time - self._curr_spike_pickup_stamp)

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
                    self.players[p].update_current_round(RoundVec.OUTCOME.value, 1)
                else:
                    self.players[p].update_current_round(RoundVec.OUTCOME.value, -1)

                # Set time alive
                if self.players[p].get_current_round_val(RoundVec.DEAD.value) == 0:
                    self.players[p].add_current_round(RoundVec.TIME_ALIVE.value, round_length)

                # Normalize spike time
                spike_time = self.players[p].get_current_round_val(RoundVec.SPIKE_CARRY_PERCENT.value)
                self.players[p].update_current_round(RoundVec.SPIKE_CARRY_PERCENT.value, spike_time / round_length)


            round_end_stamp = float(event['metadata']['eventTime']['omittingPauses'][:-1])
            while 'snapshot' not in event:
                event = self.event_feed.popleft()

            e = event['snapshot']

            # Set combat score
            for p in e['players']:
                player = str(p['playerId']['value'])
                self.players[player].update_current_round(RoundVec.COMBAT_SCORE.value, p['scores']['combatScore']['roundScore'])

            self._processing_round = False
            self._curr_round_start_time = None
            self._curr_spike_carrier = None
            self._curr_spike_pickup_stamp = None
            self._curr_round_start_time = None
            return


    def __init__(self, file):
        assert(os.path.isfile(file))
        self.file = file
        self.players = dict()
        self.teams = dict()
        self._curr_round_start_time = None
        self._curr_spike_carrier = None
        self._curr_spike_pickup_stamp = None
        self._curr_round_start_time = None
        self._processing_round = False

        logging.critical(f"Reading game {self.file.split('/')[-1]}")
        with open(self.file, 'r') as f:
            # TODO: look into msgspec or similar instead of native json parsing, takes like 10-20 sec to load a game
            j = json.load(f)
        logging.info("Done reading json")

        self.event_feed = deque(j)

        first_event = self.event_feed.popleft()

        self.game_id = first_event['platformGameId']

        players = mapping_df.loc[mapping_df['platformGameId'] == self.game_id, 'participantMapping'].values[0]
        for i, p in enumerate(players.values()):
            self.players[str(i+1)] = PlayerGame(p)

        second_event = self.event_feed.popleft()

        self.map = maps[second_event['configuration']['selectedMap']['fallback']['displayName']]

        teamid = str(second_event['configuration']['teams'][0]['teamId']['value'])
        self.teams[teamid] = dict()
        self.teams[teamid]['players'] = [p['value'] for p in second_event['configuration']['teams'][0]['playersInTeam']]
        self.teams[teamid]['name'] = team_df.iloc[second_event['configuration']['teams'][0]['teamId']['value']]['slug']

        teamid = str(second_event['configuration']['teams'][1]['teamId']['value'])
        self.teams[teamid] = dict()
        self.teams[teamid]['players'] = [p['value'] for p in second_event['configuration']['teams'][1]['playersInTeam']]
        self.teams[teamid]['name'] = team_df.iloc[second_event['configuration']['teams'][1]['teamId']['value']]['slug']

        # ingest events
        logging.info("Ingesting events...")
        with tqdm(total=len(self.event_feed)) as pbar:
            while len(self.event_feed) != 0:
                start_len = len(self.event_feed)
                current_event = self.event_feed.popleft()
                self._process_event(current_event)
                pbar.update(start_len - len(self.event_feed))
        logging.info("Done ingesting events")

        # ingestion post processing
        logging.info("Processing data...")
        # for p in tqdm(self.players):
        #     self.players[p].calculate_game_vec()
        logging.info("Done processing data")