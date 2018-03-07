# Man AHL HiveMinder 2017

This repo is forked from the [main HiveMinder repo](https://github.com/manahl/hiveminder), which contains an implementation of the game that was used in the Man AHL Coder Prize 2017 competition. This fork contains my submission to the competition (in algos/matts_algo.py) which was good enough to get to the final but not enough to place in the top 3.

Some links:
* [https://www.ahl.com/coderprize](https://www.ahl.com/coderprize)
* [https://www.man.com/man-ahl-announces-coder-prize-winners-2017](https://www.man.com/man-ahl-announces-coder-prize-winners-2017)

HiveMinder is a turn-based game played on a hexagonal board where, amongst other actions, players aim to direct bees to transfer nectar from flowers to hives and avoid collisions with other bees. The challenge in the original competition was to write an algorithmic player to compete head to head against other submissions. Algorithms have a maximum of 200 milliseconds to return their move otherwise the opportunity to move is void.

To setup use:

    git clone https://github.com/mkerin/hiveminder.git
    cd hiveminder

To run the game in your browser:

    python game.py

Or to run the simulation:

    python simulate.py

I would expect algos/matts_algo.py to be competitive with the algos/winner.py in simulations without bee_traps, but for algos/winners.py to pull ahead as soon as bee_traps are introduced.

Note that there is some variance in the relative scores achieved by the different algorithms between runs. This is particularly due to the fact that borders are porous; bees traveling over the edge of one board will appear on an adjacent board and hence being next to a random algorithm which tends to let go of 'good' items will be advantageous.

Approach:
* My algorithm is built around a depth first search to forecast future consequences of actions taken now, and to choose the move with maximal potential gain.

Major efficiency improvements:
* Transposition tables  
A priori I don't know how deep I can search and still return an answer within the time limit. Hence I search for the best move at depth 1, at depth 2, at depth 3 etc whilst checking how much time I've used up, and then return the best answer so far as soon as I get 'close' to the time limit. Obviously this is wasteful as I have to start at the top of the tree each time. To counter this I use tranposition tables so that when I re-evaluate the same state at a depth <= the previous search I can just return the value from the transposition table.
* Removing bloat from Seed/Bee/QueenBee objects  
To evaluate the consequence of a given move I create a new board state reflecting the outcome of that move. This involves a lot of copying - or in our case converting to a json string and back. Using __copy__ constructors would have been nicer.. lets call it a legacy issue. As coded up by the ManAHL developers each Bee/QueenBee/Seed carries it's own copy of the game parameters. Turns out its quite a lot quicker to just refer to a single global GameParameters object if you're intending to create a lot of copies of these objects.

Lessons learnt:
* In hindsight I focused too much on making my algorithm fast. Speed is useful because it lets you forecast further ahead, but due to the stochastic nature of some events in the game this means that the potential future state gets further away from how the actual future state.
* It's much easier to program under pressure when you have an existing suite of unit tests.
