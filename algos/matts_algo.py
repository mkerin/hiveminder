from hiveminder import algo_player
from hiveminder.game_params import DEFAULT_GAME_PARAMETERS, GameParameters
from hiveminder.hive import Hive
# from tools.bee import Bee, QueenBee
# from tools.seed import Seed

# from matts_tools.my_flower import Flower
# from matts_tools.my_volant import Volant
# from matts_tools.my_bee import Bee
from matts_tools.my_node_json import MyNodeJson

from random import choice
from copy import copy
import sys

from collections import namedtuple
from datetime import datetime, timedelta


ScoreParameters = namedtuple("ScoreParams", [
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


def _ret_range_coords(center, size, limit):
    min_n, max_n = max(center - size, 0), min(center + size, limit)
    return range(min_n, max_n)


def footprint(hive, size):
    """Return valid tiles within 'size' of hive location."""
    return [(x, y) for x in _ret_range_coords(hive[0], size, 8)
            for y in _ret_range_coords(hive[1], size, 8)]


def dfs_max_score(node, depth, hash_table):
    """Max score from depth first search at fixed depth."""
    if depth == 0:
        return node.score

    best_value = -10000
    key = hash(node)
    if key in hash_table and hash_table[key]["depth"] >= depth:
        best_value = hash_table[key]["score"]
    else:
        for child in node.children:
            v = dfs_max_score(child, depth - 1, hash_table)
            best_value = max(best_value, v)

        hash_table[key] = dict(cmd=node.cmd, depth=depth, score=best_value)
    return best_value


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
        dfs_max_score at fixed depth. Unsure why.

    """
    TIME_LIMIT = timedelta(microseconds=160000)
    then = datetime.now()
    hash_table = {}

    # PREPROCESSING - slightly hacky edit to pass single DEFAULT_GAME_PARAMLETERS pointer
    for vol_json in inflight.values():
        if vol_json[0] == "Bee" or vol_json[0] == "QueenBee":
            vol_json[5] = DEFAULT_GAME_PARAMETERS

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
                v = (dfs_max_score(child, depth - 1, hash_table), command)
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
