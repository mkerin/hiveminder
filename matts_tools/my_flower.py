from __future__ import absolute_import, division
import sys
from hiveminder.flower import Flower


class Flower(object):
    """ Flower object without copy of game_params.

    It turns out that keeping a copy of the game_params dict in every counter
    on the board is incredibly slow.
    """
    def __init__(self, x, y, game_params, potency=1, visits=0, expires=None):
        self.x = x
        self.y = y
        self.potency = potency
        self.visits = visits
        self.expires = expires

    def to_json(self):
        return [self.x, self.y, None, self.potency, self.visits, self.expires,
                self.__class__.__name__]

    @classmethod
    def from_json(cls, json):
        # return cls(json[0], json[1], None, *json[3:-1])
        module_location = {'Flower': 'my_flower', 'VenusBeeTrap': 'my_venus_bee_trap'}
        name = json[-1]
        # if "" not in name:
        #     name = "" + name
        new_flower_class = getattr(sys.modules['matts_tools.' + module_location[name]], name)
        return new_flower_class(json[0], json[1], None, *json[3:-1])

    __hash__ = None

    def visit(self, game_params):
        self.visits += 1
        self.expires += game_params.flower_lifespan_visit_impact
        self.potency = min(3, self.visits // game_params.flower_visit_potency_ratio + 1)

        # Return True if we make a seed
        return (self.visits >= game_params.flower_seed_visit_initial_threshold and
                self.visits % game_params.flower_seed_visit_subsequent_threshold == 0)
