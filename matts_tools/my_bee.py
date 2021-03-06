from matts_tools.my_volant import Volant
from hiveminder.hive import Hive


class Bee(Volant):
    def __init__(self, x, y, heading, energy, game_params, nectar=0):
        super(Bee, self).__init__(x, y, heading)
        self.energy = energy
        self.nectar = nectar
        self.game_params = game_params

    def advance(self, reverse=False):
        bee = super(Bee, self).advance(reverse)
        bee.energy -= 1 if self.nectar < self.game_params.bee_nectar_capacity else 2
        return bee

    def _new_from_xyh(self, x, y, h):
        return type(self)(x, y, h, self.energy, self.game_params, self.nectar)

    def drink(self, nectar):
        self.nectar = min(self.game_params.bee_nectar_capacity, self.nectar + nectar)
        self.energy = self.energy + self.game_params.bee_energy_boost_per_nectar * nectar

    def to_json(self):
        return super(Bee, self).to_json() + [self.energy, self.game_params, self.nectar]

    @classmethod
    def from_json(cls, json):
        return cls(*json[1:-2], game_params=json[-2], nectar=json[-1])


class QueenBee(Bee):
    def create_hive(self, board):
        # add hive where queen is. destroy any existing hive.
        # should only happen if a newly launched queen hives immediately where she is launched
        board.hives = [h for h in board.hives if h.x != self.x or h.y != self.y] + [Hive(self.x, self.y, self.nectar)]
