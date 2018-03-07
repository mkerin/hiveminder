from hiveminder.headings import heading_to_delta, OPPOSITE_HEADINGS
from hiveminder._util import is_even
from hiveminder.headings import LEGAL_NEW_HEADINGS
from hiveminder.hive import Hive

from matts_tools.my_volant import Seed
from matts_tools.my_bee import Bee, QueenBee
from matts_tools.my_flower import Flower


def _del_at_coordinate(items, x, y):
    return tuple(item for item in items if (item.x, item.y) != (x, y))


def volant_from_json(json):
    name = json[0]
    return {'Seed': Seed, 'Bee': Bee, 'QueenBee': QueenBee}[name].from_json(json)


class LiteBoard(object):
    """Lightweight re-implementation of hiveminder.board object. Also aims to remove stochasticity.

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
            launch_seed = flower.visit(self.game_params)
            if launch_seed:
                self.seeds_to_gen += 1

    def move_volants(self):
        for volant_id, volant in self.inflight.items():
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

    @classmethod
    def from_json(cls, json):
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
