from hiveminder import algo_player
from hiveminder.game_params import DEFAULT_GAME_PARAMETERS, GameParameters
from hiveminder.hive import Hive
# from tools.flower import Flower
# from tools.bee import Bee, QueenBee
from hiveminder.headings import LEGAL_NEW_HEADINGS
# from tools.seed import Seed
from hiveminder.headings import heading_to_delta, OPPOSITE_HEADINGS
from hiveminder._util import is_even

from random import choice
from copy import copy

from collections import namedtuple
from datetime import datetime, timedelta

poss_headings = {0: [60, -60],
                 60: [120, 0],
                 120: [180, 60],
                 180: [-120, 120],
                 -120: [-60, 180],
                 -60: [0, -120], }

ScoreParameters = namedtuple("ScoreParams",[
    "is_oncourse",
    "seeds_spawned",
    "laden_and_oncourse_to_hive",
    "unladen_and_oncourse_to_flower",
    "dead_bee",
    "dead_queen",
    "nectar_carried",
    "flower_adjacent_to_hive",
    "flower_adjacent_to_flower",
    "flower_score_factor",
    "hive_score_factor",
    "dead_bee_score_factor",
    "nectar_score_factor",
    "mid_stage_graded_nectar",
    "early_stage_graded_nectar"
                         ])

MY_SCORE_PARAMS = ScoreParameters(is_oncourse=1,
                                  seeds_spawned=50,
                                  unladen_and_oncourse_to_flower=1,
                                  laden_and_oncourse_to_hive=1,
                                  dead_bee=5,
                                  dead_queen=100,
                                  nectar_carried=1,
                                  flower_adjacent_to_hive=60,
                                  flower_adjacent_to_flower=55,
                                  flower_score_factor=50,
                                  hive_score_factor=200,
                                  dead_bee_score_factor=-3,
                                  nectar_score_factor=2,
                                  mid_stage_graded_nectar=[[60, 90, 10], [4, 3, 2]],
                                  early_stage_graded_nectar=[[100], [2]])


@algo_player(name="MattsAlgo",
             description="Depth first search to find the move with maximal potential gain")
def matts_algo(board_width, board_height, hives, flowers, inflight, crashed,
                  lost_volants, received_volants, landed, scores, player_id, game_id, turn_num):
    """
    Intend to implement as much of this answer as possible:
    https://www.quora.com/How-do-I-make-Minimax-algorithm-incredibly-fast-How-do-I-deepen-the-game-search-tree

    Successful implementation depends on:
    - reducing the branching factor
    - transposition tables
    - iterative deepening

    Implimented Ideas:
    - [scoring] node._graded_nectar_score()
        intended to incentivize half-filling hives during mid game.

    - [scoring] flower placement
        flowers preferentially placed next to hives or next to flowers in mid game.

    - [speed up] edit to volant.advance()
        change internal state and return self. Avoids creating a new object. No logical errors witnessed.

    - [speed up] edit to LiteBoard.detect_crashes()
        opposing_states.add() no longer copies volants. -10ms at depth 3?

    - [speed up] edit to bee.drink()
        this just changes bee's internal state rather than return a new bee

    - [speed up] edit to flower.to_json() / from_json()
        huge performance gain when we no longer pass game parameters with each object

    Shelved Ideas:
    - [speed up] edit to volant.advance()
        attempted to change the volants internal state instead of returning new objects. This changes the result of
        minimax at fixed depth. Unsure why.

    """
    TIME_LIMIT = timedelta(microseconds=160000)
    then = datetime.now()
    table = {}

    # PREPROCESSING - slightly hacky edit to pass single DEFAULT_GAME_PARAMLETERS pointer
    for vol_json in inflight.values():
        if vol_json[0] == "Bee" or vol_json[0] == "QueenBee":
            vol_json[5] = DEFAULT_GAME_PARAMETERS

    # FUNCTIONS
    def _ret_range_coords(center, size, limit):
        min_n, max_n = max(center - size, 0), min(center + size, limit)
        return range(min_n, max_n)

    def footprint(hive, size):
        return [(x, y) for x in _ret_range_coords(hive[0], size, 8)
                for y in _ret_range_coords(hive[1], size, 8)]

    def minimax(node, depth):
        if depth == 0:
            return node.score

        best_value = -10000
        key = hash(node)
        if key in table and table[key]["depth"] >= depth:
            best_value = table[key]["score"]
        else:
            for child in node.children:
                v = minimax(child, depth - 1)
                best_value = max(best_value, v)

            table[key] = dict(cmd=node.cmd, depth=depth, score=best_value)

        return best_value

    ## SCRIPTING
    if inflight:

        # Detect game stage here
        if len(hives) <= 5:
            game_stage = "early"
        else:
            game_stage = "mid"

        # Generate sets of tiles adjacent to hives / flowers
        hive_locations = {(h[0], h[1]) for h in hives}
        flower_locations = {(f[0], f[1]) for f in flowers}

        hive_footprint = {(x, y) for hive in hives for x, y in footprint(hive, 1)}
        flower_footprint = {(x, y) for flower in flowers for x, y in footprint(flower, 1)}

        adjacent_to_hives = hive_footprint - hive_locations
        adjacent_to_flowers = flower_footprint - hive_locations


        # object edit - orig
        node = MyNodeJson(board_width=board_width,
                          board_height=board_height,
                          hives=hives,
                          flowers=flowers,
                          inflight=inflight,
                          turn_num=turn_num,
                          game_params=DEFAULT_GAME_PARAMETERS,
                          dead_bees=0,
                          cmd=None,
                          my_score_params=MY_SCORE_PARAMS,
                          game_stage=game_stage,
                          adjacent_to_flowers=adjacent_to_flowers,
                          adjacent_to_hives=adjacent_to_hives)

        # node = MyNodeJson(board_width=board_width,
        #                   board_height=board_height,
        #                   hives = [(Hive(*i)) for i in hives],
        #                   flowers=[Flower.from_json(i) for i in flowers],
        #                   inflight={volant_id: volant_from_json(volant) for volant_id, volant in
        #                             inflight.items()},
        #                   turn_num=turn_num,
        #                   game_params=DEFAULT_GAME_PARAMETERS,
        #                   cmd=None,
        #                   my_score_params=MY_SCORE_PARAMS)

        best_combo = (-10000, "No move better than -1000 found")
        bf_price = {"Bee": 2, "Seed": 3, "QueenBee": 3}
        bf = sum([bf_price[vol[0]] for _, vol in inflight.items()])

        for depth in range(1, 20):

            first_eval_at_new_depth = True

            for command in node.potential_moves:

                start_of_most_recent_eval = datetime.now()
                if first_eval_at_new_depth:
                    start_of_first_eval = datetime.now()

                child = node.get_child(command)
                v = (minimax(child, depth - 1), command)
                best_combo = max(best_combo, v, key=lambda x: x[0])

                # Return best result if evaluation of next branch predicted to breach time limit
                cost_of_most_recent_eval = datetime.now() - start_of_most_recent_eval
                cost_of_most_recent_eval = timedelta(microseconds=1.5 * cost_of_most_recent_eval.microseconds)
                if (datetime.now() + cost_of_most_recent_eval - then) > TIME_LIMIT:
                    _, cmd = best_combo
                    return cmd

                if first_eval_at_new_depth:
                    cost_of_first_eval = (datetime.now() - start_of_first_eval)
                    first_eval_at_new_depth = False

            _, cmd = best_combo

            # Return best result if first branch of new search at increased depth predicted to breach time limit
            if ((datetime.now() - then) > TIME_LIMIT) or (datetime.now() - then + cost_of_first_eval * bf > TIME_LIMIT):
                return cmd

        return cmd
    else:
        return None


@matts_algo.on_start_game
def start_game(board_width, board_height, hives, flowers, players, player_id, game_id, game_params):
    """
    Called once at the start of the game to inform the algorithm of the starting state of the game
    """
    pass


@matts_algo.on_game_over
def game_over(board_width, board_height, hives, flowers, inflight, crashed,
              lost_volants, received_volants, landed, scores, player_id, game_id, turns):
    """
    Called at the end of the game to inform the algorithm with the result of the final turn
    """
    pass


def _del_at_coordinate(items, x, y):
    return tuple(item for item in items if (item.x, item.y) != (x, y))


def volant_from_json(json):
    return {'Seed': Seed, 'Bee': Bee, 'QueenBee': QueenBee}[json[0]].from_json(json)


class LiteBoard(object):
    """
    Lightweight board object. Also aims to remove stochasticity.

    Changelog:
    - __init__()
        delete mention of neighbours - don't use

    - calculate_score()
        delete - don't use

    - visit_flowers()
        instead of generating new seed, we call self.seeds_to_gen += 1

    - send_volants()
        Just delete volants that are off the board rather than adding to neighbour
        :returns: empty dict instead of dict of sent volants

    - receive_volants()
        Deleted.
        All received volants should already be contained in inflight.

    - launch_bees()
        Deleted.
        No point in launching bees. Instead hive bonus as soon as hive.nectar > queen_bee_bonus


    """
    def __init__(self,
                 game_params,
                 board_width,
                 board_height,
                 hives,
                 flowers,
                 inflight=None,
                 dead_bees=0,
                 seeds_to_gen=0):
        self.game_params = game_params
        self.board_width = board_width
        self.board_height = board_height
        self.hives = hives
        self.flowers = flowers
        self.inflight = inflight or {}
        self.dead_bees = dead_bees
        self.seeds_to_gen = seeds_to_gen
        self._incoming = {}

    def make_turn(self, cmd, turn_num):
        self.apply_command(cmd, turn_num)
        self.remove_dead_flowers(turn_num)
        self.move_volants()
        self.send_volants()
        self.visit_flowers()
        self.land_bees()
        self.detect_crashes()

    def detect_crashes(self):
        bee_occupied = {}
        seed_occupied = {}
        opposing_states = set()  # Used to look for head on collisions
        for volant_id, volant in self.inflight.items():
            if isinstance(volant, Bee):
                bee_occupied.setdefault((volant.x, volant.y), set()).add(volant_id)

                reverse_heading = OPPOSITE_HEADINGS[volant.heading]
                reverse_dx, reverse_dy = heading_to_delta(reverse_heading, is_even(volant.x))
                opposing_states.add((volant.x + reverse_dx, volant.y + reverse_dy, reverse_heading))

                # opposing_states.add(copy(volant).advance(reverse=True).xyh)
            elif isinstance(volant, Seed):
                seed_occupied.setdefault((volant.x, volant.y), set()).add(volant_id)

        collided = {bee for _, bees in bee_occupied.items() for bee in bees if len(bees) > 1}
        exhaused = {bee_id for bee_id, bee in self.inflight.items()
                    if isinstance(bee, Bee) and bee.energy < 0} - collided
        headon = {bee_id for bee_id, bee in self.inflight.items()
                  if isinstance(bee, Bee) and bee.xyh in opposing_states} - exhaused - collided
        self.dead_bees += len(collided) + len(exhaused) + len(headon)

        seeds_collided = {seed for _, seeds in seed_occupied.items() for seed in seeds if len(seeds) > 1}

        return dict(collided={bee_id: self.inflight.pop(bee_id) for bee_id in collided},
                    exhausted={bee_id: self.inflight.pop(bee_id) for bee_id in exhaused},
                    headon={bee_id: self.inflight.pop(bee_id) for bee_id in headon},
                    seeds={seed_id: self.inflight.pop(seed_id) for seed_id in seeds_collided},)

    def land_bees(self):
        hives = {(hive.x, hive.y): hive for hive in self.hives}

        landed = {bee_id: hives[bee.x, bee.y] for bee_id, bee in self.inflight.items()
                  if isinstance(bee, Bee) and (bee.x, bee.y) in hives}

        for bee_id, hive in landed.items():
            inflight_volant = self.inflight[bee_id]
            if isinstance(inflight_volant, QueenBee):
                self.dead_bees += 1
            else:
                hive.nectar += self.inflight[bee_id].nectar

        return {bee_id: self.inflight.pop(bee_id) for bee_id in landed}

    def visit_flowers(self):
        flowers = {(flower.x, flower.y): flower for flower in self.flowers}

        vists = {bee_id: flowers[bee.x, bee.y] for bee_id, bee in self.inflight.items()
                 if isinstance(bee, Bee) and (bee.x, bee.y) in flowers}

        for bee_id, flower in vists.items():
            self.inflight[bee_id].drink(flower.potency)
            # drink - edit
            # self.inflight[bee_id] = self.inflight[bee_id].drink(flower.potency)
            #  asdict - edit
            launch_seed = flower.visit(self.game_params)
            # launch_seed = flower.visit()
            if launch_seed:
                self.seeds_to_gen += 1

    def move_volants(self):
        for volant_id, volant in self.inflight.items():
            # volant.advance()
            self.inflight[volant_id] = volant.advance()

    def send_volants(self):

        sent = dict()
        for volant_id, volant in self.inflight.items():
            if volant.x < 0 or volant.x >= self.board_width or volant.y < 0 or volant.y >= self.board_height:
                new_x = (self.board_width + volant.x) % self.board_width
                new_y = (self.board_height + volant.y) % self.board_height

                receiver = "Other"
                sent[volant_id] = (receiver, volant.set_position(new_x, new_y))

        for volant_id, routing in sent.items():
            del self.inflight[volant_id]

        # return {volant_id: volant for (volant_id, (_, volant)) in sent.items()}
        return {}

    def apply_command(self, cmd, turn_num):
        if cmd is not None and cmd["command"] is not None:
            cmd_volant_id, cmd_heading = cmd['entity'], cmd['command']

            if cmd_volant_id not in self.inflight:
                raise RuntimeError("Unknown entity.")

            cmd_volant = self.inflight[cmd_volant_id]

            if isinstance(cmd_volant, Seed) and cmd_heading == "flower":
                # If there is already a hive or a flower on this tile remove it
                self.hives = _del_at_coordinate(self.hives, cmd_volant.x, cmd_volant.y)
                self.flowers = _del_at_coordinate(self.flowers, cmd_volant.x, cmd_volant.y)

                # Add new flower
                self.flowers += (Flower(cmd_volant.x, cmd_volant.y, self.game_params,
                                        expires=turn_num + self.game_params.flower_lifespan),)
                del self.inflight[cmd_volant_id]
            elif isinstance(cmd_volant, QueenBee) and 'create_hive' == cmd_heading:
                try:
                    # If there is a flower on this tile remove it
                    self.flowers = _del_at_coordinate(self.flowers, cmd_volant.x, cmd_volant.y)
                    cmd_volant.create_hive(self)
                    del self.inflight[cmd_volant_id]
                except Exception as e:
                    raise RuntimeError("Can not create hive for this bee {} {}".format(cmd_volant, e))
            elif cmd_heading not in LEGAL_NEW_HEADINGS[cmd_volant.heading]:
                raise RuntimeError("Can not rotate to heading '{}' from heading '{}'.".format(cmd_heading,
                                                                                              cmd_volant.heading))
            else:
                cmd_volant.heading = cmd_heading

    def remove_dead_flowers(self, turn_num):
        for flower in self.flowers:
            if flower.expires is None:
                raise RuntimeError("Flower expiry is None")

        unexpired_flowers = tuple(flower for flower in self.flowers if flower.expires > turn_num)

        # If there are no flowers left on the board we need to keep at least one!
        if unexpired_flowers:
            self.flowers = unexpired_flowers
        elif self.flowers:
            self.flowers = (choice(self.flowers),)

    def to_json(self):
        return {"boardWidth": self.board_width,
                "boardHeight": self.board_height,
                "hives": [hive.to_json() for hive in self.hives],
                "flowers": [flower.to_json() for flower in self.flowers],
                "inflight": {volant_id: volant.to_json() for volant_id, volant in self.inflight.items()},
                "deadBees": self.dead_bees,
                "seedsToGen": self.seeds_to_gen}
                # "gameParams": self.game_params._asdict()}

    @classmethod
    def from_json(cls, json):
        # game_params=GameParameters(**json["gameParams"])
        return cls(board_width=json["boardWidth"],
                   board_height=json["boardHeight"],
                   hives=tuple(Hive(*hive) for hive in json["hives"]),
                   flowers=tuple(Flower.from_json(flower) for flower in json["flowers"]),
                   inflight={volant_id: volant_from_json(volant) for volant_id, volant in json["inflight"].items()},
                   dead_bees=json["deadBees"],
                   seeds_to_gen=json["seedsToGen"])

    __hash__ = None

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            def filter_dict(d):
                """
                Filter out attributes starting with '_', in particular _neighbours as it
                creates circular references and isn't fundamental to a board's state
                """
                return {k: v for k, v in d.items() if not k.startswith('_')}
            return filter_dict(self.__dict__) == filter_dict(other.__dict__)
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, self.__class__):
            return not self.__eq__(other)
        return NotImplemented

# object edit - orig
class MyNodeJson:
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


class Volant(object):
    def __init__(self, x, y, heading):
        self.x = x
        self.y = y
        self.heading = heading

    def _new_from_xyh(self, x, y, h):
        return type(self)(x, y, h)

    def to_json(self):
        return [self.__class__.__name__, self.x, self.y, self.heading]

    def advance(self, reverse=False):
        heading = OPPOSITE_HEADINGS[self.heading] if reverse else self.heading
        dx, dy = heading_to_delta(heading, is_even(self.x))
        self.x += dx
        self.y += dy
        self.heading = heading
        return self
        # return self._new_from_xyh(self.x + dx, self.y + dy, heading)

    def set_position(self, x, y):
        return self._new_from_xyh(x, y, self.heading)

    @property
    def xyh(self):
        return self.x, self.y, self.heading

    @classmethod
    def from_json(cls, json):
        return cls(*json[1:])

    __hash__ = None

    def __eq__(self, other):
        if isinstance(other, Volant):
            return self.to_json() == other.to_json()
        else:
            return NotImplemented

    def __ne__(self, other):
        if isinstance(other, Volant):
            return self.to_json() != other.to_json()
        else:
            return NotImplemented

    def __repr__(self):
        return '{0}({1})'.format(self.__class__.__name__, ", ".join(map(repr, self.to_json()[1:])))

class Flower(object):
    def __init__(self, x, y, game_params, potency=1, visits=0, expires=None):
        self.x = x
        self.y = y
        # self.game_params = game_params
        self.potency = potency
        self.visits = visits
        self.expires = expires

    def to_json(self):
        return [self.x, self.y, None, self.potency, self.visits, self.expires,
                self.__class__.__name__]
        # return [self.x, self.y, self.game_params._asdict(), self.potency, self.visits, self.expires]

    @classmethod
    def from_json(cls, json):
        return cls(json[0], json[1], None, *json[3:-1])
        # return cls(json[0], json[1], GameParameters(**json[2]), *json[3:])

    __hash__ = None

    def __eq__(self, other):
        if isinstance(other, Flower):
            return self.to_json() == other.to_json()
        else:
            return NotImplemented

    def __ne__(self, other):
        if isinstance(other, Flower):
            return self.to_json() != other.to_json()
        else:
            return NotImplemented

    def __repr__(self):
        return "Flower({})".format(", ".join(map(repr, self.to_json())))

    def visit(self, game_params):
        self.visits += 1
        self.expires += game_params.flower_lifespan_visit_impact
        self.potency = min(3, self.visits // game_params.flower_visit_potency_ratio + 1)

        # Return True if we make a seed
        return (self.visits >= game_params.flower_seed_visit_initial_threshold and
                self.visits % game_params.flower_seed_visit_subsequent_threshold == 0)

class Bee(Volant):
    def __init__(self, x, y, heading, energy, game_params, nectar=0):
        super(Bee, self).__init__(x, y, heading)
        self.energy = energy
        self.nectar = nectar
        self.game_params = game_params

    def advance(self, reverse=False):
        # super(Bee, self).advance(reverse)
        # self.energy -= 1 if self.nectar < self.game_params.bee_nectar_capacity else 2
        bee = super(Bee, self).advance(reverse)
        bee.energy -= 1 if self.nectar < self.game_params.bee_nectar_capacity else 2
        return bee

    def _new_from_xyh(self, x, y, h):
        return type(self)(x, y, h, self.energy, self.game_params, self.nectar)

    def drink(self, nectar):
        self.nectar = min(self.game_params.bee_nectar_capacity, self.nectar + nectar)
        self.energy = self.energy + self.game_params.bee_energy_boost_per_nectar * nectar
        # drink-edit
        # return type(self)(self.x,
        #                   self.y,
        #                   self.heading,
        #                   self.energy + self.game_params.bee_energy_boost_per_nectar * nectar,
        #                   self.game_params,
        #                   min(self.game_params.bee_nectar_capacity, self.nectar + nectar))

    def to_json(self):
        # return super(Bee, self).to_json() + [self.energy, self.game_params._asdict(), self.nectar]
        return super(Bee, self).to_json() + [self.energy, self.game_params, self.nectar]
        # return super(Bee, self).to_json() + [self.energy, self.game_params=None, self.nectar]

    @classmethod
    def from_json(cls, json):
        # return cls(*json[1:-2], game_params=GameParameters(**json[-2]), nectar=json[-1])
        return cls(*json[1:-2], game_params=json[-2], nectar=json[-1])
        # return cls(*json[1:-2], game_params=None, nectar=json[-1])


class QueenBee(Bee):
    def create_hive(self, board):
        # add hive where queen is. destroy any existing hive.
        # should only happen if a newly launched queen hives immediately where she is launched
        board.hives = [h for h in board.hives if h.x != self.x or h.y != self.y] + [Hive(self.x, self.y, self.nectar)]

class Seed(Volant):
    pass
