from hiveminder.hive import Hive

from matts_tools.my_bee import Bee, QueenBee
from matts_tools.my_flower import Flower
from matts_tools.my_volant import Seed
from matts_tools.lite_board import LiteBoard

poss_headings = {0: [60, -60],
                 60: [120, 0],
                 120: [180, 60],
                 180: [-120, 120],
                 -120: [-60, 180],
                 -60: [0, -120], }


def volant_from_json(json):
    name = json[0]
    return {'Seed': Seed, 'Bee': Bee, 'QueenBee': QueenBee}[name].from_json(json)


class MyNodeJson(object):
    """
    WARNING: board_height & board_width hardcoded in as 8 in self.footprint()

    Container to:
     - hold information on the game state
     - generate new possible moves
     - calculate a score heuristic

    Must also be fast to use.

    Convert from_json outside of MyNode, faster for the moment to work with class instances

    TODO: give pt bonus for hitting nectar limit, visit limit
    """

    def __init__(self, board_width, board_height, hives, flowers, inflight, turn_num, game_params, cmd,
                 my_score_params, game_stage, adjacent_to_flowers, adjacent_to_hives, dead_bees=0, seeds_to_gen=0):
        self.board_width = board_width
        self.board_height = board_height
        self.hives = hives
        self.flowers = flowers
        self.inflight = inflight
        self.turn_num = turn_num
        self.game_params = game_params
        self.dead_bees = dead_bees
        self.cmd = cmd
        self.my_score_params = my_score_params
        self.seeds_to_gen = seeds_to_gen
        self.adjacent_to_flowers = adjacent_to_flowers
        self.adjacent_to_hives = adjacent_to_hives
        self.game_stage = game_stage

    def get_child(self, cmd):
        """

        :param cmd:
        :return: child node
        """
        board = LiteBoard(game_params=self.game_params,
                      board_width=self.board_width,
                      board_height=self.board_height,
                      hives=[(Hive(*i)) for i in self.hives],
                      flowers=[Flower.from_json(i) for i in self.flowers],
                      inflight={volant_id: volant_from_json(volant) for volant_id, volant in
                                self.inflight.items()},
                      dead_bees=self.dead_bees,
                      seeds_to_gen=self.seeds_to_gen)

        board.make_turn(cmd, self.turn_num)
        board_json = board.to_json()

        board_json["turnNum"] = self.turn_num + 1
        board_json["scoreParams"] = self.my_score_params
        board_json["cmd"] = cmd

        return self.gen_child(board_json, self.game_params, self.game_stage, self.adjacent_to_flowers,
                              self.adjacent_to_hives)

    @staticmethod
    def _ret_range_coords(center, size, limit):
        min_n, max_n = max(center - size, 0), min(center + size, limit)
        return range(min_n, max_n)

    @classmethod
    def footprint(cls, hive, size):
        return [(x, y) for x in cls._ret_range_coords(hive[0], size, 8)
                for y in cls._ret_range_coords(hive[1], size, 8)]

    @property
    def potential_moves(self):
        """
        Generate potential moves to investigate.

        Pruning:
        - won't attempt to build a flower / hive on top of an existing flower / hive
        - just 1 None instead of commanding volants to move forward individually
        - if queens exist, we only consider move for them.
            WARNING: This might cause the tree of game states to behave in unexpected ways. Better to pass in at top?

        :return: list of dict(entity, command)
        """
        res = [None]
        hive_locations = {(h[0], h[1]) for h in self.hives}
        flower_footprint = {(f[0], f[1]) for f in self.flowers}
        flower_footprint.update(hive_locations)

        if len(self.hives) <= 2:
            hive_footprint = {(x, y) for hive in self.hives for x, y in self.footprint(hive, 2)}
        else:
            hive_footprint = hive_locations

        ## Pruning - generating tracked volant ids
        queens = [vol_id for vol_id, vol in self.inflight.items() if vol[0] == "QueenBee"]
        if queens:
            tracked_volant_ids = queens
        else:
            tracked_volant_ids = self.inflight.keys()

        for vol_id in tracked_volant_ids:
            if vol_id in self.inflight:
                tracked_volant = self.inflight[vol_id]

                for new_heading in poss_headings[tracked_volant[3]]:
                    res.append(dict(entity=vol_id, command=new_heading))

                if tracked_volant[0] == "QueenBee":
                    if not (tracked_volant[1], tracked_volant[2]) in hive_footprint:
                        res.append(dict(entity=vol_id, command="create_hive"))
                    elif tracked_volant[4] <= 1 and not (tracked_volant[1], tracked_volant[2] in hive_locations):
                        res.append(dict(entity=vol_id, command="create_hive"))

                elif tracked_volant[0] == "Seed" and not (tracked_volant[1], tracked_volant[2]) in flower_footprint:
                    res.append(dict(entity=vol_id, command="flower"))

        return res

    def _gen_tracked_ids(self):
        pass

    @property
    def children(self):
        res = []
        for cmd in self.potential_moves:
            res.append(self.get_child(cmd))
        return res

    @property
    def score(self):
        # All boards start with 1 hive & 1 flower;
        # board score starts at self.game_params.hive_score_factor + self.game_params.flower_score_factor
        try:
            scoring_method = getattr(self, "%s_stage_score" % self.game_stage)
        except AttributeError:
            print("Unexpected game_stage passed: ", self.game_stage)
            raise AttributeError

        return scoring_method

    @property
    def early_stage_score(self):
        """
        Things to score in the early game:
        - 200 per hive
        - 50 per flower
        - 2 per nectar in hive
        - -3 per dead bee

        - 1 per nectar in bee
        - 50 per queen bee
        - 25 per inflight seed or 2 if flowers > 40
        - 25 per future seed or 2 if flowers > 40

        :return: int
        """
        num_of_hives = len(self.hives)
        num_of_flowers = len(self.flowers)

        turn_score = (self.dead_bees * self.my_score_params.dead_bee_score_factor +
                      num_of_hives * self.my_score_params.hive_score_factor +
                      num_of_flowers * self.my_score_params.flower_score_factor +
                      sum(hive[2] for hive in self.hives) * self.my_score_params.nectar_score_factor)

        seed_bonus = 25 if num_of_flowers <= 40 else 2
        my_additions = self.seeds_to_gen * seed_bonus

        for vol in self.inflight.values():
            if vol[0] == "QueenBee":
                my_additions += 50
            elif vol[0] == "Seed":
                my_additions += seed_bonus
            else:
                my_additions += vol[6]

        return turn_score + my_additions

    @property
    def mid_stage_score(self):
        """
        - 200 per hive [can't lose incentive to build hives]
        - 50 per flower
        - graded nectar in hive [incentivize using hive capacity instead of making new]
        - -3 per dead bee

        - activate preferred flower placements
            - best next to hive
            - else next to flower
        :return: int
        """
        turn_score = (self.dead_bees * self.my_score_params.dead_bee_score_factor +
                      len(self.hives) * self.my_score_params.hive_score_factor +
                      sum(hive[2] for hive in self.hives) * self.my_score_params.nectar_score_factor +
                      sum(self._graded_nectar_score(hive[2]) for hive in self.hives))

        for flower in self.flowers:
            if (flower[0], flower[1]) in self.adjacent_to_hives:
                turn_score += self.my_score_params.flower_adjacent_to_hive
            elif (flower[0], flower[1]) in self.adjacent_to_flowers:
                turn_score += self.my_score_params.flower_adjacent_to_flower
            else:
                turn_score += self.my_score_params.flower_score_factor

        return turn_score

    def _graded_nectar_score(self, nectar):
        limits, points = getattr(self.my_score_params, "%s_stage_graded_nectar" % self.game_stage)
        res = 0
        for x in range(len(limits)):
            res += points[x] * min(nectar, limits[x])
            nectar = max(0, nectar - limits[x])
        return res

    def coord_to_index(self, x, y):
        return y * self.board_width + x

    def _key(self):
        key = [[] for i in range(self.board_width*self.board_height)]

        for h in self.hives:
            key[self.coord_to_index(h[0], h[1])].append("h%i%i%i" % (h[0], h[1], h[2]))

        for f in self.flowers:
            key[self.coord_to_index(f[0], f[1])].append("f%i%i%i" % (f[0], f[1], f[4]))

        for _, v in self.inflight.items():
            if v[0] == 'Bee' or v[0] == 'QueenBee':
                key[self.coord_to_index(v[1], v[2])].append("b%i%i%i%i%i" % (v[1], v[2], v[3], v[4], v[6]))

        for _, v in self.inflight.items():
            if v[0] == 'Seed':
                key[self.coord_to_index(v[1], v[2])].append("s%i%i%i" % (v[1], v[2], v[3]))

        key.append(["db%i" % self.dead_bees])
        key.append(["tn%i" % self.turn_num])
        key.append(["stg%i" % self.seeds_to_gen])

        # remove empty lists from key
        retval = [item for sublist in key for item in sublist]
        return tuple(retval)

    def __hash__(self):
        return hash(self._key())

    @classmethod
    def gen_child(cls, board_json, game_params, game_stage, adj_to_flwrs, adj_to_hives):
        return cls(board_width=board_json["boardWidth"],
                   board_height=board_json["boardHeight"],
                   hives=board_json["hives"],
                   flowers=board_json["flowers"],
                   inflight=board_json["inflight"],
                   turn_num=board_json["turnNum"],
                   game_params=game_params,
                   dead_bees=board_json["deadBees"],
                   cmd=board_json["cmd"],
                   my_score_params=board_json["scoreParams"],
                   seeds_to_gen=board_json["seedsToGen"],
                   game_stage=game_stage,
                   adjacent_to_flowers=adj_to_flwrs,
                   adjacent_to_hives=adj_to_hives)
