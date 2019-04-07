#!/usr/bin/env python3

import gym
import torch
import random
import numpy as np
from torch import optim
from torch import nn
from torch.distributions import Normal
import cherry as ch
from cherry import envs

ACTION_DISCRETISATION = 5
ACTION_NOISE = 0.1
BACKTRACK_COEFF = 0.8
BACKTRACK_ITERS = 10
CONJUGATE_GRADIENT_ITERS = 10
DAMPING_COEFF = 0.1
DISCOUNT = 0.99
EPSILON = 0.05
ENTROPY_WEIGHT = 0.2
HIDDEN_SIZE = 32
KL_LIMIT = 0.05
LEARNING_RATE = 0.001
MAX_STEPS = 100000
BATCH_SIZE = 2048
POLICY_DELAY = 2
POLYAK_FACTOR = 0.995
PPO_CLIP_RATIO = 0.2
PPO_EPOCHS = 20
REPLAY_SIZE = 100000
TARGET_ACTION_NOISE = 0.2
TARGET_ACTION_NOISE_CLIP = 0.5
TARGET_UPDATE_INTERVAL = 2500
TRACE_DECAY = 0.97
UPDATE_INTERVAL = 1
UPDATE_START = 10000
TEST_INTERVAL = 1000
SEED = 42

random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)


class Actor(nn.Module):
    def __init__(self, hidden_size, stochastic=True, layer_norm=False):
        super().__init__()
        layers = [nn.Linear(3, hidden_size), nn.Tanh(), nn.Linear(hidden_size, hidden_size), nn.Tanh(), nn.Linear(hidden_size, 1)]
        if layer_norm:
            layers = layers[:1] + [nn.LayerNorm(hidden_size)] + layers[1:3] + [nn.LayerNorm(hidden_size)] + layers[3:]  # Insert layer normalisation between fully-connected layers and nonlinearities
        self.policy = nn.Sequential(*layers)
        if stochastic:
            self.policy_log_std = nn.Parameter(torch.tensor([[0.]]))

    def forward(self, state):
        policy = self.policy(state)
        return policy


class Critic(nn.Module):
    def __init__(self, hidden_size, state_action=False, layer_norm=False):
        super().__init__()
        self.state_action = state_action
        layers = [nn.Linear(3 + (1 if state_action else 0), hidden_size), nn.Tanh(), nn.Linear(hidden_size, hidden_size), nn.Tanh(), nn.Linear(hidden_size, 1)]
        if layer_norm:
            layers = layers[:1] + [nn.LayerNorm(hidden_size)] + layers[1:3] + [nn.LayerNorm(hidden_size)] + layers[3:]  # Insert layer normalisation between fully-connected layers and nonlinearities
        self.value = nn.Sequential(*layers)

    def forward(self, state, action=None):
        if self.state_action:
            value = self.value(torch.cat([state, action], dim=1))
        else:
            value = self.value(state)
        return value.squeeze(dim=1)


class ActorCritic(nn.Module):
    def __init__(self, hidden_size):
        super().__init__()
        self.actor = Actor(hidden_size, stochastic=True)
        self.critic = Critic(hidden_size)

    def forward(self, state):
        policy = Normal(self.actor(state), self.actor.policy_log_std.exp())
        value = self.critic(state)
        return policy, value


def get_action(state):
        mass, value = agent(state)
        action = mass.sample()
        log_prob = mass.log_prob(action)
        return action, {
                'log_prob': log_prob,
                'value': value,
        }


agent = ActorCritic(HIDDEN_SIZE)
actor_optimiser = optim.Adam(agent.actor.parameters(), lr=LEARNING_RATE)
critic_optimiser = optim.Adam(agent.critic.parameters(), lr=LEARNING_RATE)

env = gym.make('Pendulum-v0')
env.seed(SEED)
env = envs.Torch(env)
env = envs.Runner(env)
replay = ch.ExperienceReplay()

for step in range(1, MAX_STEPS + 1):

    replay += env.run(get_action, episodes=1)
    if len(replay) > BATCH_SIZE:
        with torch.no_grad():
            advantages = ch.rewards.generalized_advantage(DISCOUNT,
                                                          TRACE_DECAY,
                                                          replay.rewards,
                                                          replay.dones,
                                                          replay.values,
                                                          torch.zeros(1))
            advantages = ch.utils.normalize(advantages, epsilon=1e-8)
            returns = ch.rewards.discount(DISCOUNT,
                                          replay.rewards,
                                          replay.dones)

        print(step)
        # Policy loss
        log_probs = replay.log_probs
        policy_loss = ch.algorithms.a2c.policy_loss(log_probs, advantages)
        actor_optimiser.zero_grad()
        policy_loss.backward()
        actor_optimiser.step()
        print('ploss', policy_loss.item())

        # Value loss
        value_loss = ch.algorithms.a2c.state_value_loss(replay.values, returns)
        critic_optimiser.zero_grad()
        value_loss.backward()
        critic_optimiser.step()
        print('vloss', value_loss.item())

        print('')
        replay.empty()
