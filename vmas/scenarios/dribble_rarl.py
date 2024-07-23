#  Copyright (c) 2022-2024.
#  ProrokLab (https://www.proroklab.org/)
#  All rights reserved.
import typing
from typing import List

import math
import operator
from functools import reduce

import torch

from vmas import render_interactively
from vmas.simulator.core import Agent, Box, Landmark, Line, Sphere, World
from vmas.simulator.dynamics.holonomic_with_rot import HolonomicWithRotation
from vmas.simulator.scenario import BaseScenario
from vmas.simulator.utils import Color, X, Y

if typing.TYPE_CHECKING:
    from vmas.simulator.rendering import Geom

class Scenario(BaseScenario):
    def make_world(self, batch_dim: int, device: torch.device, **kwargs):
        self.init_params(**kwargs)
        world = self.init_world(batch_dim, device)
        self.init_agents(world)
        self.init_ball(world)
        self.init_background(world)
        self.init_walls(world)
        # self.init_goals(world)
        self.init_areas(world)
        self.init_target(world)
        self._done = torch.zeros(batch_dim, device=device, dtype=torch.bool)
        self.math = Math()
        return world

    def reset_world_at(self, env_index: int = None):
        self.reset_ball(env_index)
        self.reset_agents(env_index)
        self.reset_background(env_index)
        self.reset_walls(env_index)
        # self.reset_goals(env_index)
        self.reset_areas(env_index)
        self.reset_target(env_index)
        self.reset_controllers(env_index)
        if env_index is None:
            self._done[:] = False
        else:
            self._done[env_index] = False

    def init_params(self, **kwargs):
        self.viewer_size = kwargs.get("viewer_size", (1200, 800))

        self.ai_red_agents = kwargs.get("ai_red_agents", False)
        self.ai_blue_agents = kwargs.get("ai_blue_agents", False)
        
        self.n_blue_agents = kwargs.get("n_blue_agents", 1)
        self.n_red_agents = kwargs.get("n_red_agents", 1)
        self.agent_size = kwargs.get("agent_size", 0.05)
        self.goal_size = kwargs.get("goal_size", 0.35)
        self.goal_depth = kwargs.get("goal_depth", 0.1)
        self.area_size = kwargs.get("area_size", 0.35)
        self.area_depth = kwargs.get("area_depth", 0.1)
        self.pitch_length = kwargs.get("pitch_length", 3.0)
        self.pitch_width = kwargs.get("pitch_width", 1.5)
        self.max_speed = kwargs.get("max_speed", 0.15)
        self.u_multiplier = kwargs.get("u_multiplier", 0.1)
        self.ball_max_speed = kwargs.get("ball_max_speed", 0.3)
        self.ball_mass = kwargs.get("ball_mass", 1.0)
        self.ball_size = kwargs.get("ball_size", 0.02)
        self.n_traj_points = kwargs.get("n_traj_points", 8)
        self.n_traj_points = kwargs.get("n_target_points", 2)

        self.dist_reward_ratio = kwargs.get("dist_reward_ratio", 0.01)
        self.agent_ball_vactor_reward_ratio = kwargs.get("agent_ball_vactor_reward_ratio", 1.0)
        self.dribbled_reward_ratio = kwargs.get("dribbled_reward_ratio", 1.0)
        self.goal_dist_reward_ratio = kwargs.get("goal_dist_reward_ratio", 0.0)
        self.ball_target_vactor_reward_ratio = kwargs.get("ball_target_vactor_reward_ratio", 0.5)
        self.reached_target_reward_ratio = kwargs.get("reached_target_reward_ratio", 0.1)
        self.area_reward_ratio = kwargs.get("area_reward_ratio", 0.01)


    def init_world(self, batch_dim: int, device: torch.device):
        # Make world
        world = World(
            batch_dim,
            device,
            dt=0.1,
            drag=0.05,
            x_semidim=self.pitch_length / 2 - self.agent_size,
            y_semidim=self.pitch_width / 2 - self.agent_size,
        )
        world.agent_size = self.agent_size
        world.pitch_width = self.pitch_width
        world.pitch_length = self.pitch_length
        world.goal_size = self.goal_size
        world.goal_depth = self.goal_depth
        return world

    def init_agents(self, world):
        # Add agents
        # self.blue_controller = AgentPolicy(team="Blue")
        # self.red_controller = AgentPolicy(team="Red")

        self.blue_controller = None
        self.red_controller = None

        blue_agents = []
        for i in range(self.n_blue_agents):
            agent = Agent(
                name=f"agent_blue_{i}",
                shape=Sphere(radius=self.agent_size),
                # action_script=self.blue_controller.run if self.ai_blue_agents else None,
                color=Color.BLUE,
                render_action=True,
                max_speed=self.max_speed,
                u_range=[1, 1, 1],
                u_multiplier=[0.25, 0.25, 0.002],
                mass=4.0,
                dynamics=HolonomicWithRotation(),
            )
            world.add_agent(agent)
            blue_agents.append(agent)

        red_agents = []
        for i in range(self.n_red_agents):
            agent = Agent(
                name=f"agent_red_{i}",
                shape=Sphere(radius=self.agent_size),
                # action_script=self.red_controller.run if self.ai_red_agents else None,
                color=Color.RED,
                render_action=True,
                max_speed=self.max_speed,
                u_range=[1, 1, 1],
                u_multiplier=[0.25, 0.25, 0.002],
                mass=4.0,
                dynamics=HolonomicWithRotation(),
            )
            world.add_agent(agent)
            red_agents.append(agent)

        self.red_agents = red_agents
        self.blue_agents = blue_agents
        self.active_red_agents_num = self.n_red_agents - 1
        self.active_blue_agents_num = self.n_blue_agents - 1
        world.red_agents = red_agents
        world.blue_agents = blue_agents

    def reset_agents(self, env_index: int = None):
        for i, agent in enumerate(self.blue_agents):
            agent.set_pos(
                torch.rand(
                    (
                        (1, self.world.dim_p)
                        if env_index is not None
                        else (self.world.batch_dim, self.world.dim_p)
                    ),
                    device=self.world.device,
                )
                * torch.tensor(
                    [
                        self.pitch_length - self.agent_size *8,
                        self.pitch_width - self.agent_size *8
                    ],
                    device=self.world.device,
                )
                + torch.tensor(
                    [-self.pitch_length / 2 + self.agent_size * 4, -self.pitch_width / 2  + self.agent_size * 4],
                    device=self.world.device,
                ),
                batch_index=env_index,
            )

            agent.set_vel(
                torch.zeros(2, device=self.world.device),
                batch_index=env_index,
            )
            agent.set_rot(
                torch.tensor(
                    torch.rand(1).item() * 2 * math.pi,  # 0から2 * πの間でランダムな角度を生成
                    dtype=torch.float32,
                    device=self.world.device,
                ),
                batch_index=env_index,
            )
            agent.set_ang_vel(
                torch.tensor(
                    0,
                    dtype=torch.float32,
                    device=self.world.device,
                ),
                batch_index=env_index,
            )
            agent.set_dribble(
                torch.zeros(
                    1,
                    dtype=torch.bool,
                    device=self.world.device),
                batch_index=env_index,
            )
        
        for agent in self.red_agents:
            agent.set_pos(
                torch.rand(
                    (
                        (1, self.world.dim_p)
                        if env_index is not None
                        else (self.world.batch_dim, self.world.dim_p)
                    ),
                    device=self.world.device,
                )
                * torch.tensor(
                    [
                        self.pitch_length - self.agent_size *8,
                        self.pitch_width - self.agent_size *8
                    ],
                    device=self.world.device,
                )
                + torch.tensor(
                    [-self.pitch_length / 2 + self.agent_size * 4, -self.pitch_width / 2  + self.agent_size * 4],
                    device=self.world.device,
                ),
                batch_index=env_index,
            )
            agent.set_vel(
                torch.zeros(2, device=self.world.device),
                batch_index=env_index,
            )
            agent.set_rot(
                torch.tensor(
                    torch.rand(1).item() * 2 * math.pi,  # 0から2 * πの間でランダムな角度を生成
                    dtype=torch.float32,
                    device=self.world.device,
                ),
                batch_index=env_index,
            )
            agent.set_ang_vel(
                torch.tensor(
                    0,
                    dtype=torch.float32,
                    device=self.world.device,
                ),
                batch_index=env_index,
            )
            agent.set_dribble(
                torch.zeros(
                    1,
                    dtype=torch.bool,
                    device=self.world.device),
                batch_index=env_index,
            )
    def reset_controllers(self, env_index: int = None):
        if self.red_controller is not None:
            if not self.red_controller.initialised:
                self.red_controller.init(self.world)
            self.red_controller.reset(env_index)
        if self.blue_controller is not None:
            if not self.blue_controller.initialised:
                self.blue_controller.init(self.world)
            self.blue_controller.reset(env_index)

    def init_ball(self, world):
        # Add Ball
        ball = Agent(
            name="Ball",
            shape=Sphere(radius=self.ball_size),
            action_script=self.ball_action_script,
            max_speed=self.ball_max_speed,
            mass=self.ball_mass,
            color=Color.GRAY
        )
        world.add_agent(ball)
        world.ball = ball
        self.ball = ball

    def reset_ball(self, env_index: int = None):
        self.ball.set_pos(
            torch.rand(
                (
                    (1, self.world.dim_p)
                    if env_index is not None
                    else (self.world.batch_dim, self.world.dim_p)
                ),
                device=self.world.device,
            )
            * torch.tensor(
                [
                    self.pitch_length - self.agent_size *8,
                    self.pitch_width - self.agent_size *8
                ],
                device=self.world.device,
            )
            + torch.tensor(
                [-self.pitch_length / 2 + self.agent_size * 4, -self.pitch_width / 2  + self.agent_size * 4],
                device=self.world.device,
            ),
            batch_index=env_index,
        )
        self.ball.set_vel(
            torch.zeros(2, device=self.world.device),
            batch_index=env_index,
        )
        self.ball.set_dribble(
            torch.zeros(1, dtype=torch.bool, device=self.world.device),
            batch_index=env_index,
        )
        

    def init_background(self, world):
        centre_line = Landmark(
            name="Centre Line",
            collide=False,
            movable=False,
            shape=Line(length=self.pitch_width - 2 * self.agent_size),
            color=Color.WHITE,
        )
        world.add_landmark(centre_line)

        right_line = Landmark(
            name="Right Line",
            collide=False,
            movable=False,
            shape=Line(length=self.pitch_width - 2 * self.agent_size),
            color=Color.WHITE,
        )
        world.add_landmark(right_line)

        left_line = Landmark(
            name="Left Line",
            collide=False,
            movable=False,
            shape=Line(length=self.pitch_width - 2 * self.agent_size),
            color=Color.WHITE,
        )
        world.add_landmark(left_line)

        top_line = Landmark(
            name="Top Line",
            collide=False,
            movable=False,
            shape=Line(length=self.pitch_length - 2 * self.agent_size),
            color=Color.WHITE,
        )
        world.add_landmark(top_line)

        bottom_line = Landmark(
            name="Bottom Line",
            collide=False,
            movable=False,
            shape=Line(length=self.pitch_length - 2 * self.agent_size),
            color=Color.WHITE,
        )
        world.add_landmark(bottom_line)

    def reset_background(self, env_index: int = None):
        for landmark in self.world.landmarks:
            if landmark.name == "Centre Line":
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Right Line":
                landmark.set_pos(
                    torch.tensor(
                        [self.pitch_length / 2 - self.agent_size, 0.0],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Left Line":
                landmark.set_pos(
                    torch.tensor(
                        [-self.pitch_length / 2 + self.agent_size, 0.0],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Top Line":
                landmark.set_pos(
                    torch.tensor(
                        [0.0, self.pitch_width / 2 - self.agent_size],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Bottom Line":
                landmark.set_pos(
                    torch.tensor(
                        [0.0, -self.pitch_width / 2 + self.agent_size],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )

    def init_walls(self, world):
        right_top_wall = Landmark(
            name="Right Top Wall",
            collide=True,
            movable=False,
            shape=Line(
                length=self.pitch_width / 2 - self.agent_size - self.goal_size / 2,
            ),
            color=Color.WHITE,
        )
        world.add_landmark(right_top_wall)

        left_top_wall = Landmark(
            name="Left Top Wall",
            collide=True,
            movable=False,
            shape=Line(
                length=self.pitch_width / 2 - self.agent_size - self.goal_size / 2,
            ),
            color=Color.WHITE,
        )
        world.add_landmark(left_top_wall)

        right_bottom_wall = Landmark(
            name="Right Bottom Wall",
            collide=True,
            movable=False,
            shape=Line(
                length=self.pitch_width / 2 - self.agent_size - self.goal_size / 2,
            ),
            color=Color.WHITE,
        )
        world.add_landmark(right_bottom_wall)

        left_bottom_wall = Landmark(
            name="Left Bottom Wall",
            collide=True,
            movable=False,
            shape=Line(
                length=self.pitch_width / 2 - self.agent_size - self.goal_size / 2,
            ),
            color=Color.WHITE,
        )
        world.add_landmark(left_bottom_wall)

    def reset_walls(self, env_index: int = None):
        for landmark in self.world.landmarks:
            if landmark.name == "Left Top Wall":
                landmark.set_pos(
                    torch.tensor(
                        [
                            -self.pitch_length / 2,
                            self.pitch_width / 4 + self.goal_size / 4,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )

            elif landmark.name == "Left Bottom Wall":
                landmark.set_pos(
                    torch.tensor(
                        [
                            -self.pitch_length / 2,
                            -self.pitch_width / 4 - self.goal_size / 4,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )

            elif landmark.name == "Right Top Wall":
                landmark.set_pos(
                    torch.tensor(
                        [
                            self.pitch_length / 2,
                            self.pitch_width / 4 + self.goal_size / 4,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Right Bottom Wall":
                landmark.set_pos(
                    torch.tensor(
                        [
                            self.pitch_length / 2,
                            -self.pitch_width / 4 - self.goal_size / 4,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )

    def init_goals(self, world):
        right_goal_back = Landmark(
            name="Right Goal Back",
            collide=True,
            movable=False,
            shape=Line(length=self.goal_size),
            color=Color.WHITE,
        )
        world.add_landmark(right_goal_back)

        left_goal_back = Landmark(
            name="Left Goal Back",
            collide=True,
            movable=False,
            shape=Line(length=self.goal_size),
            color=Color.WHITE,
        )
        world.add_landmark(left_goal_back)

        right_goal_top = Landmark(
            name="Right Goal Top",
            collide=True,
            movable=False,
            shape=Line(length=self.goal_depth),
            color=Color.WHITE,
        )
        world.add_landmark(right_goal_top)

        left_goal_top = Landmark(
            name="Left Goal Top",
            collide=True,
            movable=False,
            shape=Line(length=self.goal_depth),
            color=Color.WHITE,
        )
        world.add_landmark(left_goal_top)

        right_goal_bottom = Landmark(
            name="Right Goal Bottom",
            collide=True,
            movable=False,
            shape=Line(length=self.goal_depth),
            color=Color.WHITE,
        )
        world.add_landmark(right_goal_bottom)

        left_goal_bottom = Landmark(
            name="Left Goal Bottom",
            collide=True,
            movable=False,
            shape=Line(length=self.goal_depth),
            color=Color.WHITE,
        )
        world.add_landmark(left_goal_bottom)

        blue_net = Landmark(
            name="Blue Net",
            collide=False,
            movable=False,
            shape=Box(length=self.goal_depth, width=self.goal_size),
            color=(0.5, 0.5, 0.5, 0.5),
        )
        world.add_landmark(blue_net)

        red_net = Landmark(
            name="Red Net",
            collide=False,
            movable=False,
            shape=Box(length=self.goal_depth, width=self.goal_size),
            color=(0.5, 0.5, 0.5, 0.5),
        )
        world.add_landmark(red_net)

        self.blue_net = blue_net
        self.red_net = red_net
        world.blue_net = blue_net
        world.red_net = red_net

    def reset_goals(self, env_index: int = None):
        for landmark in self.world.landmarks:
            if landmark.name == "Left Goal Back":
                landmark.set_pos(
                    torch.tensor(
                        [
                            -self.pitch_length / 2 - self.goal_depth + self.agent_size,
                            0.0,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Right Goal Back":
                landmark.set_pos(
                    torch.tensor(
                        [
                            self.pitch_length / 2 + self.goal_depth - self.agent_size,
                            0.0,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
                landmark.set_rot(
                    torch.tensor(
                        [torch.pi / 2],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Left Goal Top":
                landmark.set_pos(
                    torch.tensor(
                        [
                            -self.pitch_length / 2
                            - self.goal_depth / 2
                            + self.agent_size,
                            self.goal_size / 2,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Left Goal Bottom":
                landmark.set_pos(
                    torch.tensor(
                        [
                            -self.pitch_length / 2
                            - self.goal_depth / 2
                            + self.agent_size,
                            -self.goal_size / 2,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Right Goal Top":
                landmark.set_pos(
                    torch.tensor(
                        [
                            self.pitch_length / 2
                            + self.goal_depth / 2
                            - self.agent_size,
                            self.goal_size / 2,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Right Goal Bottom":
                landmark.set_pos(
                    torch.tensor(
                        [
                            self.pitch_length / 2
                            + self.goal_depth / 2
                            - self.agent_size,
                            -self.goal_size / 2,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Red Net":
                landmark.set_pos(
                    torch.tensor(
                        [
                            self.pitch_length / 2
                            + self.goal_depth / 2
                            - self.agent_size / 2,
                            0.0,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Blue Net":
                landmark.set_pos(
                    torch.tensor(
                        [
                            -self.pitch_length / 2
                            - self.goal_depth / 2
                            + self.agent_size / 2,
                            0.0,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )


    def init_areas(self, world):
        top_lim_area = Landmark(
            name="Top Limit Area",
            collide=False,
            movable=False,
            shape=Box(length=self.pitch_length - self.agent_size * 2, width=self.agent_size),
            color=(0.5, 0.5, 0.5, 0.5),
            )
        world.add_landmark(top_lim_area)

        self.top_lim_area = top_lim_area
        world.top_lim_area = top_lim_area

        bottom_lim_area = Landmark(
            name="Bottom Limit Area",
            collide=False,
            movable=False,
            shape=Box(length=self.pitch_length - self.agent_size * 2, width=self.agent_size),
            color=(0.5, 0.5, 0.5, 0.5),
            )
        world.add_landmark(bottom_lim_area)

        self.bottom_lim_area = bottom_lim_area
        world.bottom_lim_area = bottom_lim_area

        right_lim_area = Landmark(
            name="Right Limit Area",
            collide=False,
            movable=False,
            shape=Box(length=self.agent_size, width=self.pitch_width - self.agent_size * 2),
            color=(0.5, 0.5, 0.5, 0.5),
            )
        world.add_landmark(right_lim_area)

        self.right_lim_area = right_lim_area
        world.right_lim_area = right_lim_area

        left_lim_area = Landmark(
            name="Left Limit Area",
            collide=False,
            movable=False,
            shape=Box(length=self.agent_size, width=self.pitch_width - self.agent_size * 2),
            color=(0.5, 0.5, 0.5, 0.5),
            )
        world.add_landmark(left_lim_area)

        self.left_lim_area = left_lim_area
        world.left_lim_area = left_lim_area


    def reset_areas(self, env_index: int = None):
        for landmark in self.world.landmarks:
            if landmark.name == "Top Limit Area":
                landmark.set_pos(
                    torch.tensor(
                        [
                            0.0,
                            self.pitch_width / 2 - self.agent_size,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            elif landmark.name == "Bottom Limit Area":
                landmark.set_pos(
                    torch.tensor(
                        [
                            0.0,
                            - self.pitch_width / 2 + self.agent_size,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            if landmark.name == "Right Limit Area":
                landmark.set_pos(
                    torch.tensor(
                        [
                            self.pitch_length / 2
                            - self.agent_size,
                            0.0,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )
            if landmark.name == "Left Limit Area":
                landmark.set_pos(
                    torch.tensor(
                        [
                            - self.pitch_length / 2
                            + self.agent_size,
                            0.0,
                        ],
                        dtype=torch.float32,
                        device=self.world.device,
                    ),
                    batch_index=env_index,
                )

    def init_target(self, world):
        blue_target = Landmark(
            name="Blue_Target",
            collide=False,
            movable=False,
            shape=Sphere(radius=self.agent_size),
            color=Color.BLUE,
        )
        world.add_landmark(blue_target)
        # self.target = blue_target
        red_target = Landmark(
            name="Red_Target",
            collide=False,
            movable=False,
            shape=Sphere(radius=self.agent_size),
            color=Color.RED,
        )
        world.add_landmark(red_target)
        # self.target = red_target

        self.blue_target = blue_target
        self.red_target = red_target
        world.blue_target = blue_target
        world.red_target = red_target

    def reset_target(self, env_index: int = None):
        self.blue_target.set_pos(
            torch.rand(
                (
                    (1, self.world.dim_p)
                    if env_index is not None
                    else (self.world.batch_dim, self.world.dim_p)
                ),
                device=self.world.device,
            )
            * torch.tensor(
                [
                    self.pitch_length - self.agent_size *8,
                    self.pitch_width - self.agent_size *8
                ],
                device=self.world.device,
            )
            + torch.tensor(
                [-self.pitch_length / 2 + self.agent_size * 4, -self.pitch_width / 2  + self.agent_size * 4],
                device=self.world.device,
            ),
            batch_index=env_index,
        )
        self.red_target.set_pos(
            torch.rand(
                (
                    (1, self.world.dim_p)
                    if env_index is not None
                    else (self.world.batch_dim, self.world.dim_p)
                ),
                device=self.world.device,
            )
            * torch.tensor(
                [
                    self.pitch_length - self.agent_size *8,
                    self.pitch_width - self.agent_size *8
                ],
                device=self.world.device,
            )
            + torch.tensor(
                [-self.pitch_length / 2 + self.agent_size * 4, -self.pitch_width / 2  + self.agent_size * 4],
                device=self.world.device,
            ),
            batch_index=env_index,
        )

    def reward(self, agent: Agent):
        if "agent" in agent.name:
            # import ipdb; ipdb.set_trace()
            self._done = torch.tensor([False], device=self.world.device).expand(self.world.batch_dim)
            dribble_env_indices = torch.where(agent.state.dribble == torch.tensor([True],device=self.world.device))[0]
                
            # RARL reward
            if agent == self.blue_agents[0]:
                self._reward = self.protagonistic_reward(agent, dribble_env_indices)
                # print(f"blue agent reward || {self._reward}")
            elif agent == self.red_agents[0]:
                self._reward = self.adversarial_reward(agent, dribble_env_indices)
                # print(f"red agent reward || {self._reward}")
            
        return self._reward
        

    def protagonistic_reward(self, agent: Agent, dribble_env_indices):
        ball_dist_reward = torch.zeros(self.world.batch_dim, device=self.world.device)
        agent_ball_vector_dot = torch.zeros(self.world.batch_dim, device=self.world.device)
        dribbled_reward = torch.zeros(self.world.batch_dim, device=self.world.device)
        ball_target_vector_dot = torch.zeros(self.world.batch_dim, device=self.world.device)
        reached_target = torch.zeros(self.world.batch_dim, dtype=torch.bool, device=self.world.device)
        area_reward = torch.zeros(self.world.batch_dim, dtype=torch.bool, device=self.world.device)

        if len(dribble_env_indices) > 0:
            dribbled_reward[dribble_env_indices] = 0.1
            agent_ball_vector_dot[dribble_env_indices] = 0

            direction_vector = self.blue_target.state.pos[dribble_env_indices] - self.ball.state.pos[dribble_env_indices]
            direction_norm = torch.norm(direction_vector) + 1e-6
            normalized_direction = direction_vector / direction_norm
            ball_target_vector_dot[dribble_env_indices] = torch.clamp( 
                                                                torch.bmm(normalized_direction.unsqueeze(1), 
                                                                    self.ball.state.vel[dribble_env_indices].unsqueeze(2)).squeeze(-1).squeeze(-1)
                                                                , min=0.0)
            reached_target[dribble_env_indices] = self.world.is_overlapping(self.blue_agents[0], self.blue_target)[dribble_env_indices]
            
            area_reward[dribble_env_indices] = self.world.is_overlapping(self.blue_agents[0], self.top_lim_area)[dribble_env_indices]
            area_reward[dribble_env_indices] += self.world.is_overlapping(self.blue_agents[0], self.bottom_lim_area)[dribble_env_indices]
            area_reward[dribble_env_indices] += self.world.is_overlapping(self.blue_agents[0], self.right_lim_area)[dribble_env_indices]
            area_reward[dribble_env_indices] += self.world.is_overlapping(self.blue_agents[0], self.left_lim_area)[dribble_env_indices]
        
            
        else:
            ball_dist_reward = torch.clamp(1 / torch.linalg.vector_norm(self.blue_agents[0].state.pos - self.ball.state.pos, dim=1),
                                    max=10.0)
            # agent to ball dot reward
            direction_vector = self.ball.state.pos - agent.state.pos
            direction_norm = torch.norm(direction_vector) + 1e-6
            normalized_direction = direction_vector / direction_norm                         
            agent_ball_vector_dot = torch.clamp(
                                        torch.bmm(normalized_direction.unsqueeze(1), 
                                                    agent.state.vel.unsqueeze(2)).squeeze(-1).squeeze(-1),
                                        min = 0.0)

        _reward = ball_dist_reward * self.dist_reward_ratio + \
                    agent_ball_vector_dot * self.agent_ball_vactor_reward_ratio + \
                    dribbled_reward * self.dribbled_reward_ratio + \
                    ball_target_vector_dot * self.ball_target_vactor_reward_ratio + \
                    reached_target * self.reached_target_reward_ratio - \
                    area_reward * self.area_reward_ratio

        return _reward

    def adversarial_reward(self, agent: Agent, dribble_env_indices):
        ball_dist_reward = torch.zeros(self.world.batch_dim, device=self.world.device)
        agent_ball_vector_dot = torch.zeros(self.world.batch_dim, device=self.world.device)
        dribbled_reward = torch.zeros(self.world.batch_dim, device=self.world.device)
        ball_target_vector_dot = torch.zeros(self.world.batch_dim, device=self.world.device)
        reached_target = torch.zeros(self.world.batch_dim, dtype=torch.bool, device=self.world.device)
        area_reward = torch.zeros(self.world.batch_dim, dtype=torch.bool, device=self.world.device)
        
        # if self.world.batch_dim == 1:
        if len(dribble_env_indices) > 0:
            dribbled_reward[dribble_env_indices] = 0.1
            agent_ball_vector_dot[dribble_env_indices] = 0

            direction_vector = self.red_target.state.pos[dribble_env_indices] - self.ball.state.pos[dribble_env_indices]
            direction_norm = torch.norm(direction_vector) + 1e-6
            normalized_direction = direction_vector / direction_norm
            ball_target_vector_dot[dribble_env_indices]  = torch.clamp( 
                                                                    torch.bmm(normalized_direction.unsqueeze(1), 
                                                                                self.ball.state.vel[dribble_env_indices].unsqueeze(2)).squeeze(-1).squeeze(-1)
                                                                , min=0.0)
            reached_target[dribble_env_indices] = self.world.is_overlapping(self.red_agents[0], self.red_target)[dribble_env_indices]
            area_reward[dribble_env_indices] = self.world.is_overlapping(self.blue_agents[0], self.top_lim_area)[dribble_env_indices]
            area_reward[dribble_env_indices] += self.world.is_overlapping(self.blue_agents[0], self.bottom_lim_area)[dribble_env_indices]
            area_reward[dribble_env_indices] += self.world.is_overlapping(self.blue_agents[0], self.right_lim_area)[dribble_env_indices]
            area_reward[dribble_env_indices] += self.world.is_overlapping(self.blue_agents[0], self.left_lim_area)[dribble_env_indices]
        else:
            ball_dist_reward = torch.clamp(1 / torch.linalg.vector_norm(self.red_agents[0].state.pos - self.ball.state.pos, dim=1),
                                max=10.0)
            # agent to ball dot reward
            direction_vector = self.ball.state.pos - agent.state.pos
            direction_norm = torch.norm(direction_vector) + 1e-6
            normalized_direction = direction_vector / direction_norm
            agent_ball_vector_dot = torch.clamp( 
                                                torch.bmm(normalized_direction.unsqueeze(1), 
                                                            agent.state.vel.unsqueeze(2)).squeeze(-1).squeeze(-1)
                                            , min=0.0)

        _reward = ball_dist_reward * self.dist_reward_ratio + \
                    agent_ball_vector_dot * self.agent_ball_vactor_reward_ratio + \
                    dribbled_reward * self.dribbled_reward_ratio + \
                    ball_target_vector_dot * self.ball_target_vactor_reward_ratio + \
                    reached_target * self.reached_target_reward_ratio - \
                    area_reward * self.area_reward_ratio
    
        return _reward

    
    # def observation(self, agent: Agent):
    #     for a in self.world.agents:
    #         if a != agent:
    #             rel = a.state.pos - agent.state.pos
        
    #     if agent.name == "agent_blue_0":
    #         targe_error = self.blue_target.state.pos - agent.state.pos,
    #     else:
    #         targe_error = self.red_target.state.pos - agent.state.pos,

    #     local_axised_ball_pos = self.math.world_to_local(agent.state.pos, agent.state.rot, self.ball.state.pos)
    #     local_axised_target_pos = self.math.world_to_local(agent.state.pos, agent.state.rot, self.blue_target.state.pos)
    #     agent_rot = agent.state.rot % (2 * math.pi)
    #     obs = torch.cat(
    #         [
    #             agent_rot,
    #             agent.state.ang_vel,
    #             agent.state.dribble,
    #             self.ball.state.pos - agent.state.pos,
    #             rel,
    #             targe_error[0], # remove tuple
    #             self.ball.state.vel - agent.state.vel,
    #         ],
    #         dim=1,
    #     )
    #     return obs

    def observation(self, agent: Agent):
        for a in self.world.agents:
            if a != agent:
                # rel = a.state.pos - agent.state.pos
                local_axised_rel = self.math.world_to_local(agent.state.pos, agent.state.rot, a.state.pos)
        
        if agent.name == "agent_blue_0":
            # targe_error = self.blue_target.state.pos - agent.state.pos,
            local_axised_ball_pos = self.math.world_to_local(agent.state.pos, agent.state.rot, self.ball.state.pos)
            local_axised_target_pos = self.math.world_to_local(agent.state.pos, agent.state.rot, self.blue_target.state.pos)
            agent_rot = agent.state.rot % (2 * math.pi)

            obs = torch.cat(
                [
                    agent_rot,
                    agent.state.ang_vel,
                    local_axised_ball_pos,
                    local_axised_target_pos,
                    local_axised_rel,
                    agent.state.vel,
                    agent.state.dribble,
                ],
                dim=1,
            )
        
        else:
            # targe_error = self.red_target.state.pos - agent.state.pos,
            local_axised_ball_pos = self.math.world_to_local(agent.state.pos, agent.state.rot, self.ball.state.pos)
            local_axised_target_pos = self.math.world_to_local(agent.state.pos, agent.state.rot, self.red_target.state.pos)
            agent_rot = agent.state.rot % (2 * math.pi)
        

            obs = torch.cat(
                [
                    agent_rot,
                    agent.state.ang_vel,
                    local_axised_ball_pos,
                    local_axised_target_pos,
                    local_axised_rel,
                    agent.state.vel,
                    agent.state.dribble,
                ],
                dim=1,
            )
        return obs

    # def observation(self, agent: Agent):
        
    #     agent_rot = agent.state.rot % (2 * math.pi)
    #     obs = torch.cat(
    #         [
    #             self.ball.state.pos - agent.state.pos,
    #             self.blue_target.state.pos - agent.state.pos,
    #             agent_rot,
    #             agent.state.vel,
    #             agent.state.ang_vel,
    #             agent.state.dribble
    #         ],
    #         dim=1,
    #     )
    #     return obs

    # def observation(self, agent: Agent):
    #     local_axised_ball_pos = self.math.world_to_local(agent.state.pos, agent.state.rot, self.ball.state.pos)
    #     local_axised_target_pos = self.math.world_to_local(agent.state.pos, agent.state.rot, self.blue_target.state.pos)
    #     agent_rot = agent.state.rot % (2 * math.pi)
    #     obs = torch.cat(
    #         [
    #             local_axised_ball_pos,
    #             local_axised_target_pos,
    #             agent_rot,
    #             agent.state.vel,
    #             agent.state.ang_vel,
    #             agent.state.dribble
    #         ],
    #         dim=1,
    #     )
    #     return obs


    def done(self):
        if self.ai_blue_agents and self.ai_red_agents:
            self.reward(None)
        return self._done


    def extra_render(self, env_index: int = 0) -> "List[Geom]":
        from vmas.simulator import rendering

        geoms: List[Geom] = []
        # Agent rotation
        for i, agent in enumerate(self.world.agents):
            if "agent" in agent.name and agent.name != "Ball":
                color = Color.BLACK.value
                line = rendering.Line(
                    (0, 0),
                    (0.1, 0),
                    width=1,
                )
                xform = rendering.Transform()
                xform.set_rotation(agent.state.rot[env_index])
                xform.set_translation(*agent.state.pos[env_index])
                line.add_attr(xform)
                line.set_color(*color)
                geoms.append(line)
            else:
                pass

        # Trajectory goal circle
        color = Color.BLACK.value
        # shape=Sphere(radius=self.goal_size / 2),
        circle = rendering.make_circle(self.goal_size / 2, filled=False)
        xform = rendering.Transform()
        circle.add_attr(xform)
        xform.set_translation(0, 0)
        circle.set_color(*color)
        geoms.append(circle)

        return geoms


    # Ball Physics
    def ball_action_script(self, ball, world):
        # Avoid getting stuck against the wall
        dist_thres = world.agent_size * 2
        vel_thres = 0.1
        impulse = 0.01
        upper = (
            1
            - torch.minimum(
                world.pitch_width / 2 - ball.state.pos[:, 1],
                torch.tensor(dist_thres, device=world.device),
            )
            / dist_thres
        )
        lower = (
            1
            - torch.minimum(
                world.pitch_width / 2 + ball.state.pos[:, 1],
                torch.tensor(dist_thres, device=world.device),
            )
            / dist_thres
        )
        right = (
            1
            - torch.minimum(
                world.pitch_length / 2 - ball.state.pos[:, 0],
                torch.tensor(dist_thres, device=world.device),
            )
            / dist_thres
        )
        left = (
            1
            - torch.minimum(
                world.pitch_length / 2 + ball.state.pos[:, 0],
                torch.tensor(dist_thres, device=world.device),
            )
            / dist_thres
        )
        vertical_vel = (
            1
            - torch.minimum(
                torch.abs(ball.state.vel[:, 1]),
                torch.tensor(vel_thres, device=world.device),
            )
            / vel_thres
        )
        horizontal_vel = (
            1
            - torch.minimum(
                torch.abs(ball.state.vel[:, 1]),
                torch.tensor(vel_thres, device=world.device),
            )
            / vel_thres
        )
        dist_action = torch.stack([left - right, lower - upper], dim=1)
        vel_action = torch.stack([horizontal_vel, vertical_vel], dim=1)
        actions = dist_action * vel_action * impulse
        goal_mask = (ball.state.pos[:, 1] < world.goal_size / 2) * (
            ball.state.pos[:, 1] > -world.goal_size / 2
        )
        self.ball_dribbled_action(ball, world)
        actions[goal_mask, 0] = 0
        ball.action.u = actions

    def ball_dribbled_action(self, ball, world):
        agent_dist = 0.08 
        dribblable_vel_threshold = 0.1
        inner_product_threshold = 0.9
        angular_velocity_threshold = 0.75
        release_attenuation = 0.1
        for env_index in range(world.batch_dim):
            for i, agent in enumerate(world.agents):
                if "agent" in agent.name and agent.name != "Ball":
                    # calculate the vector of the agent's rotation
                    rot_vector_x = agent_dist * torch.cos(agent.state.rot[env_index].clone().detach())
                    rot_vector_y = agent_dist * torch.sin(agent.state.rot[env_index].clone().detach())

                    rot_vector = torch.tensor([rot_vector_x, rot_vector_y], device=world.device)

                    ball_pos_vector = ball.state.pos[env_index].clone().detach() - \
                                    agent.state.pos[env_index].clone().detach()

                    relative_vel = ball.state.vel[env_index].clone().detach() - \
                                agent.state.vel[env_index].clone().detach()
                    # calculate the inner product of the ball position and the agent's rotation vector
                    inner_product = torch.dot(ball_pos_vector.squeeze(), rot_vector) / (torch.norm(ball_pos_vector) * torch.norm(rot_vector))
                    
                    # consider the ball dribbled if the inner product is greater than the threshold and the ball is slow enough
                    if inner_product >= inner_product_threshold and \
                        torch.norm(relative_vel) <= dribblable_vel_threshold and \
                        torch.norm(ball_pos_vector) <= agent_dist:
                        agent.state.dribble[env_index] = True
                        if agent == self.blue_agents[0]:
                            self.red_agents[0].state.dribble[env_index] = False
                        elif agent == self.red_agents[0]:
                            self.blue_agents[0].state.dribble[env_index] = False
                    # if the ball is over some threshold(agent.state.vel and agent.state.ang_vel),
                    # agent can't dribble the ball.
                    if agent.state.dribble[env_index]:
                        rot_vector = self.math.rotate_vector(torch.tensor([agent_dist, 0.0], device=world.device), agent.state.rot[env_index])
                        ball.state.vel[env_index] = agent.state.vel[env_index].clone()
                        ball.state.pos[env_index] = agent.state.pos[env_index].clone() + rot_vector
                        if torch.norm(ball.state.vel[env_index]) > dribblable_vel_threshold:
                            agent.state.dribble[env_index] = False
                        if torch.norm(agent.state.ang_vel[env_index]) > angular_velocity_threshold:
                            angular_velaocity_effect = torch.tensor([agent.state.ang_vel[env_index] * -torch.sin(agent.state.rot[env_index]),
                                                                    agent.state.ang_vel[env_index] * torch.cos(agent.state.rot[env_index])],
                                                                    device=world.device)
                            ball.state.vel[env_index] += angular_velaocity_effect * release_attenuation
                            agent.state.dribble[env_index]= False


class Math:
    def rotate_vector(self, vector: torch.Tensor, theta: float) -> torch.Tensor:
        rotation_matrix = torch.tensor([
            [torch.cos(theta), -torch.sin(theta)],
            [torch.sin(theta), torch.cos(theta)]
        ], device=vector.device)

        rotated_vector = torch.matmul(rotation_matrix, vector)

        return rotated_vector

    def world_to_local(self, world_vector: torch.Tensor, rot: torch.Tensor, target_vector: torch.Tensor) -> torch.Tensor:
        """Converts a point from world coordinates to local coordinates.

        Args:
            world_vector: The vector in world coordinates (2D tensor).
            agent_rot: The rotation angle of the agent in radians (scalar tensor).
            target_vector: The point to convert (2D tensor).

        Returns:
            The coordinates of the point in local coordinates (2D tensor).
        """
        # import ipdb; ipdb.set_trace()
        rot = rot.unsqueeze(-1) * 0.0
        rotation_matrix = torch.cat([torch.cos(rot), -torch.sin(rot), torch.sin(rot), torch.cos(rot)], dim=-1).view(-1, 2, 2)

        # Subtract target_vector from world_vector to get the vector from the target to the agent
        relative_vector = world_vector - target_vector

        # Transform the relative vector to local coordinates
        local_coords = torch.matmul(rotation_matrix, relative_vector.unsqueeze(-1)).squeeze(-1)

        return local_coords



# Agent Policy
# class AgentPolicy:
    def __init__(self, team="Red"):
        self.team_name = team
        self.otherteam_name = "Blue" if (self.team_name == "Red") else "Red"

        self.pos_lookahead = 0.01
        self.vel_lookahead = 0.01
        self.start_vel_mag = 0.6

        self.dribble_speed = 0.5
        self.dribble_slowdown_dist = 0.25
        self.dribble_stop_margin_vel_coeff = 0.1
        self.initial_vel_dist_behind_target_frac = 0.3
        self.ball_pos_eps = 0.08

        self.max_shoot_time = 100
        self.max_shoot_dist = 0.6
        self.valid_start_pos_angle = math.cos(torch.pi / 4)
        self.valid_start_vel_angle = math.cos(torch.pi / 4)
        self.valid_start_dist = 0.12
        self.dist_to_hit_speed = 1.7
        self.start_vel_mag_shoot = 1.0
        self.touch_eps = 0.01
        self.shoot_on_goal_dist = 0.4

        self.possession_lookahead = 0.5

        self.lane_weight = 1.0
        self.separation_weight = 0.01

        self.attack_lane_weight = 1.0
        self.attack_goal_dist_weight = 0.35
        self.attack_defender_dist_weight = 0.25
        self.weight_diff_pass_thres = 0.1

        self.passing_angle = (2 * torch.pi / 128) * 1
        self.shooting_angle = (2 * torch.pi / 128) * 3
        self.shooting_dist = self.max_shoot_dist
        self.passing_dist = self.max_shoot_dist

        self.nsamples = 1
        self.sigma = 1.0
        self.replan_margin = 0.0

        self.initialised = False

    def init(self, world):
        self.initialised = True
        self.world = world

        self.ball = self.world.ball
        if self.team_name == "Red":
            self.teammates = self.world.red_agents
            self.opposition = self.world.blue_agents
            self.own_net = self.world.red_net
            self.target_net = self.world.blue_net
        elif self.team_name == "Blue":
            self.teammates = self.world.blue_agents
            self.opposition = self.world.red_agents
            self.own_net = self.world.blue_net
            self.target_net = self.world.red_net

        self.actions = {
            agent: {
                "dribbling": torch.zeros(
                    self.world.batch_dim, device=world.device
                ).bool(),
                "shooting": torch.zeros(
                    self.world.batch_dim, device=world.device
                ).bool(),
                "pre-shooting": torch.zeros(
                    self.world.batch_dim, device=world.device
                ).bool(),
            }
            for agent in self.teammates
        }

        self.objectives = {
            agent: {
                "target_pos": torch.zeros(
                    self.world.batch_dim, self.world.dim_p, device=world.device
                ),
                "target_vel": torch.zeros(
                    self.world.batch_dim, self.world.dim_p, device=world.device
                ),
                "start_pos": torch.zeros(
                    self.world.batch_dim, self.world.dim_p, device=world.device
                ),
                "start_vel": torch.zeros(
                    self.world.batch_dim, self.world.dim_p, device=world.device
                ),
            }
            for agent in self.teammates
        }

        self.agent_possession = {
            agent: torch.zeros(self.world.batch_dim, device=world.device).bool()
            for agent in self.teammates
        }

        self.shooting_timer = {
            agent: torch.zeros(self.world.batch_dim, device=world.device).int()
            for agent in self.teammates
        }

        self.team_possession = torch.zeros(
            self.world.batch_dim, device=world.device
        ).bool()

        if len(self.teammates) == 1:
            self.role = {self.teammates[0]: 1.0}
        else:
            roles = torch.linspace(0.5, 1, len(self.teammates), device=world.device)
            self.role = {agent: roles[i] for i, agent in enumerate(self.teammates)}

    def reset(self, env_index=Ellipsis):
        for agent in self.teammates:
            self.actions[agent]["dribbling"][env_index] = False
            self.actions[agent]["shooting"][env_index] = False
            self.actions[agent]["pre-shooting"][env_index] = False
            self.objectives[agent]["target_pos"][env_index] = torch.zeros(
                self.world.dim_p, device=self.world.device
            )
            self.objectives[agent]["target_vel"][env_index] = torch.zeros(
                self.world.dim_p, device=self.world.device
            )
            self.objectives[agent]["start_pos"][env_index] = torch.zeros(
                self.world.dim_p, device=self.world.device
            )
            self.objectives[agent]["start_vel"][env_index] = torch.zeros(
                self.world.dim_p, device=self.world.device
            )

    def policy(self, agent):
        possession_mask = self.agent_possession[agent]
        shooting_mask = (
            self.actions[agent]["shooting"] | self.actions[agent]["pre-shooting"]
        )
        # Shoot
        start_shoot_mask, shoot_pos = self.can_shoot(agent)
        can_shoot_mask = (start_shoot_mask & possession_mask) | shooting_mask  # hmm
        self.shoot(agent, shoot_pos[can_shoot_mask], env_index=can_shoot_mask)
        # Passing
        self_attack_value = self.get_attack_value(self.ball)
        differential = (
            torch.ones(self_attack_value.shape[0], device=self.world.device)
            * self.weight_diff_pass_thres
        )
        for teammate in self.teammates:
            if teammate != agent:
                can_pass_mask = self.can_pass(teammate)
                teammate_attack_value = self.get_attack_value(teammate)
                better_pos_mask = (
                    teammate_attack_value - self_attack_value
                ) > differential
                pass_mask = can_pass_mask & better_pos_mask & possession_mask
                self.passto(agent, teammate, env_index=pass_mask)
        # Move without the ball
        shooting_mask = (
            self.actions[agent]["shooting"] | self.actions[agent]["pre-shooting"]
        )
        dribble_mask = possession_mask & ~shooting_mask
        move_mask = ~possession_mask & ~shooting_mask
        best_pos = self.check_better_positions(agent, role=self.role[agent])
        self.go_to(
            agent,
            pos=best_pos[move_mask],
            vel=torch.zeros(
                move_mask.sum(), self.world.dim_p, device=self.world.device
            ),
            env_index=move_mask,
        )
        # Dribble with the ball
        self.dribble_to_goal(agent, env_index=dribble_mask)
        # If other agent is passing/shooting, stay still
        other_agents_shooting = [
            self.actions[otheragent]["pre-shooting"]
            | self.actions[otheragent]["shooting"]
            for otheragent in self.teammates
            if (otheragent != agent)
        ]
        other_agent_shooting_mask = (
            self.combine_or(other_agents_shooting)
            if len(other_agents_shooting)
            else False
        )
        stay_still_mask = other_agent_shooting_mask & ~shooting_mask  # hmm
        self.go_to(
            agent,
            pos=agent.state.pos[stay_still_mask],
            vel=torch.zeros(
                stay_still_mask.sum(),
                self.world.dim_p,
                device=self.world.device,
            ),
            env_index=stay_still_mask,
        )

    def run(self, agent, world):
        self.check_possession()
        self.policy(agent)
        control = self.get_action(agent)
        control = torch.clamp(control, min=-agent.u_range, max=agent.u_range)
        agent.action.u = control * agent.u_multiplier

    def dribble_to_goal(self, agent, env_index=Ellipsis):
        self.dribble(agent, self.target_net.state.pos[env_index], env_index=env_index)

    def shoot_on_goal(self, agent, env_index=Ellipsis):
        goal_front = self.target_net.state.pos[env_index].clone()
        left_goal_mask = goal_front[:, X] < 0
        goal_front[:, X] += self.world.goal_depth / 2 * (left_goal_mask.float() * 2 - 1)
        agent_pos = agent.state.pos[env_index]
        shoot_dir = goal_front - agent_pos
        shoot_dir = shoot_dir / shoot_dir.norm(dim=-1)[:, None]
        shoot_pos = goal_front + shoot_dir * self.shoot_on_goal_dist
        self.shoot(agent, shoot_pos, env_index=env_index)
        # self.shoot(agent, torch.tensor([-0.6, 0.]).unsqueeze(0), env_index=Ellipsis)

    def passto(self, agent, agent_dest, env_index=Ellipsis):
        self.shoot(agent, agent_dest.state.pos[env_index], env_index=env_index)

    def shoot(self, agent, pos, env_index=Ellipsis):
        if isinstance(env_index, int):
            env_index = [env_index]
        self.actions[agent]["dribbling"][env_index] = False

        ball_curr_pos = self.ball.state.pos[env_index]
        agent_curr_pos = agent.state.pos[env_index]
        agent_curr_vel = agent.state.vel[env_index]

        ball_target_disp = pos - ball_curr_pos
        ball_target_dist = ball_target_disp.norm(dim=-1)
        ball_target_dir = ball_target_disp / ball_target_dist[:, None]

        agent_ball_disp = ball_curr_pos - agent_curr_pos
        agent_ball_dist = agent_ball_disp.norm(dim=-1)
        agent_ball_dir = agent_ball_disp / agent_ball_dist[:, None]
        agent_vel_dir = agent_curr_vel / agent_curr_vel.norm(dim=-1)[:, None]

        dist_maxdist_ratio = (
            torch.minimum(
                ball_target_dist,
                torch.tensor(self.max_shoot_dist, device=self.world.device),
            )
            / self.max_shoot_dist
        )

        # Determine if shooting or pre-shooting
        start_dist = self.valid_start_dist * dist_maxdist_ratio
        valid_angle_mask = (ball_target_dir * agent_ball_dir).sum(
            dim=-1
        ) > self.valid_start_pos_angle
        valid_vel_mask = (ball_target_dir * agent_vel_dir).sum(
            dim=-1
        ) > self.valid_start_vel_angle
        valid_dist_mask = agent_ball_dist > start_dist
        shooting_mask = self.actions[agent]["shooting"][env_index] | (
            valid_dist_mask & valid_angle_mask & valid_vel_mask
        )
        pre_shooting_mask = ~shooting_mask
        start_shooting_mask = (
            ~self.actions[agent]["shooting"][env_index] & shooting_mask
        ) | (~self.actions[agent]["pre-shooting"][env_index] & pre_shooting_mask)
        # start_shooting_mask = ~self.actions[agent]["pre-shooting"][env_index] & pre_shooting_mask
        self.actions[agent]["shooting"][env_index] = shooting_mask
        self.actions[agent]["pre-shooting"][env_index] = pre_shooting_mask
        self.shooting_timer[agent][
            self.combine_mask(env_index, start_shooting_mask)
        ] = 0
        self.shooting_timer[agent][
            self.actions[agent]["shooting"] | self.actions[agent]["pre-shooting"]
        ] += 1
        # self.shooting_timer[agent][self.actions[agent]["pre-shooting"]] += 1

        # Shooting
        hit_pos = ball_curr_pos - ball_target_dir * (
            self.ball.shape.radius + agent.shape.radius
        )
        hit_speed = self.dist_to_hit_speed * dist_maxdist_ratio
        hit_vel = ball_target_dir * hit_speed[:, None]
        start_vel = self.get_start_vel(hit_pos, hit_vel, agent_curr_pos, hit_speed)

        # Pre Shooting
        pre_shoot_target_pos = ball_curr_pos - ball_target_dir * start_dist[:, None]
        pre_shoot_target_vel = ball_target_dir * hit_speed[:, None]

        # Next to wall
        close_to_wall_mask = (
            self.clamp_pos(pre_shoot_target_pos, return_bool=True) & pre_shooting_mask
        )
        pre_shooting_mask = pre_shooting_mask & ~close_to_wall_mask
        self.update_dribble(
            agent,
            pos=pos.expand(len(close_to_wall_mask), -1)[close_to_wall_mask],
            env_index=self.combine_mask(env_index, close_to_wall_mask),
        )

        self.go_to(
            agent,
            pos=pre_shoot_target_pos[pre_shooting_mask],
            vel=pre_shoot_target_vel[pre_shooting_mask],
            env_index=self.combine_mask(env_index, pre_shooting_mask),
        )

        self.go_to(
            agent,
            pos=hit_pos[shooting_mask],
            vel=hit_vel[shooting_mask],
            start_vel=start_vel[shooting_mask],
            env_index=self.combine_mask(env_index, shooting_mask),
        )

        touch_dist = (ball_curr_pos - agent_curr_pos).norm(dim=-1) - (
            self.ball.shape.radius + agent.shape.radius
        )
        touch_mask = touch_dist < self.touch_eps
        full_shooting_mask = self.combine_mask(env_index, shooting_mask & touch_mask)
        self.actions[agent]["shooting"][full_shooting_mask] = False

        dist = (pos - self.ball.state.pos[env_index]).norm(dim=-1)
        reached_goal_mask = self.combine_mask(env_index, dist <= self.ball_pos_eps)
        self.actions[agent]["shooting"][reached_goal_mask] = False
        self.actions[agent]["pre-shooting"][reached_goal_mask] = False

        max_time_mask = self.shooting_timer[agent] > self.max_shoot_time
        self.actions[agent]["shooting"][max_time_mask] = False
        self.actions[agent]["pre-shooting"][max_time_mask] = False

    def dribble(self, agent, pos, env_index=Ellipsis):
        if isinstance(env_index, int):
            env_index = [env_index]
        self.actions[agent]["dribbling"][env_index] = True
        dist = (pos - self.ball.state.pos[env_index]).norm(dim=-1)
        reached_goal_mask = self.combine_mask(env_index, dist <= self.ball_pos_eps)
        self.actions[agent]["dribbling"][reached_goal_mask] = False
        dribble_mask = self.actions[agent]["dribbling"][env_index]
        curr_pos = agent.state.pos[reached_goal_mask]
        self.go_to(
            agent,
            curr_pos,
            torch.zeros(curr_pos.shape, device=self.world.device),
            env_index=reached_goal_mask,
        )
        self.update_dribble(
            agent,
            pos=pos[dribble_mask],
            env_index=self.combine_mask(
                env_index, self.actions[agent]["dribbling"][env_index]
            ),
        )

    def update_dribble(self, agent, pos, env_index=Ellipsis):
        agent_pos = agent.state.pos[env_index]
        ball_pos = self.ball.state.pos[env_index]
        ball_disp = pos - ball_pos
        ball_dist = ball_disp.norm(dim=-1)
        direction = ball_disp / ball_dist[:, None]
        hit_pos = ball_pos - direction * (self.ball.shape.radius + agent.shape.radius)
        hit_vel = direction * self.dribble_speed
        start_vel = self.get_start_vel(hit_pos, hit_vel, agent_pos, self.start_vel_mag)

        slowdown_mask = ball_dist <= self.dribble_slowdown_dist
        hit_vel[slowdown_mask, :] *= (
            ball_dist[slowdown_mask, None] / self.dribble_slowdown_dist
        )
        # start_vel[slowdown_mask,:] *= ball_dist[slowdown_mask,None] / self.dribble_slowdown_dist

        self.go_to(agent, hit_pos, hit_vel, start_vel=start_vel, env_index=env_index)

    def go_to(self, agent, pos, vel, start_vel=None, env_index=Ellipsis):
        start_pos = agent.state.pos[env_index]
        if start_vel is None:
            start_vel = self.get_start_vel(pos, vel, start_pos, self.start_vel_mag)
        self.objectives[agent]["target_pos"][env_index] = pos
        self.objectives[agent]["target_vel"][env_index] = vel
        self.objectives[agent]["start_pos"][env_index] = start_pos
        self.objectives[agent]["start_vel"][env_index] = start_vel
        # self.plot_traj(agent, env_index=env_index)

    def get_start_vel(self, pos, vel, start_pos, start_vel_mag):
        start_vel_mag = torch.as_tensor(start_vel_mag, device=self.world.device).view(
            -1,
        )
        goal_disp = pos - start_pos
        goal_dist = goal_disp.norm(dim=-1)
        vel_mag = vel.norm(dim=-1)
        vel_dir = vel.clone()
        vel_dir[vel_mag > 0] /= vel_mag[vel_mag > 0, None]
        dist_behind_target = self.initial_vel_dist_behind_target_frac * goal_dist
        target_pos = pos - vel_dir * dist_behind_target[:, None]
        target_disp = target_pos - start_pos
        target_dist = target_disp.norm(dim=1)
        start_vel_aug_dir = target_disp
        start_vel_aug_dir[target_dist > 0] /= target_dist[target_dist > 0, None]
        start_vel = start_vel_aug_dir * start_vel_mag[:, None]
        return start_vel

    def get_action(self, agent, env_index=Ellipsis):
        curr_pos = agent.state.pos[env_index, :]
        curr_vel = agent.state.vel[env_index, :]
        u_start = torch.zeros(curr_pos.shape[0], device=self.world.device)
        des_curr_pos = self.hermite(
            self.objectives[agent]["start_pos"][env_index, :],
            self.objectives[agent]["target_pos"][env_index, :],
            self.objectives[agent]["start_vel"][env_index, :],
            self.objectives[agent]["target_vel"][env_index, :],
            u=torch.minimum(
                u_start + self.pos_lookahead,
                torch.tensor(1.0, device=self.world.device),
            ),
            deriv=0,
        )
        des_curr_vel = self.hermite(
            self.objectives[agent]["start_pos"][env_index, :],
            self.objectives[agent]["target_pos"][env_index, :],
            self.objectives[agent]["start_vel"][env_index, :],
            self.objectives[agent]["target_vel"][env_index, :],
            u=torch.minimum(
                u_start + self.vel_lookahead,
                torch.tensor(1.0, device=self.world.device),
            ),
            deriv=1,
        )
        des_curr_pos = torch.as_tensor(des_curr_pos, device=self.world.device)
        des_curr_vel = torch.as_tensor(des_curr_vel, device=self.world.device)
        control = 0.5 * (des_curr_pos - curr_pos) + 0.5 * (des_curr_vel - curr_vel)
        return control

    def hermite(self, p0, p1, p0dot, p1dot, u=0.1, deriv=0):
        # Formatting
        u = u.reshape((-1,))

        # Calculation
        U = torch.stack(
            [
                self.nPr(3, deriv) * (u ** max(0, 3 - deriv)),
                self.nPr(2, deriv) * (u ** max(0, 2 - deriv)),
                self.nPr(1, deriv) * (u ** max(0, 1 - deriv)),
                self.nPr(0, deriv) * (u**0),
            ],
            dim=1,
        ).float()
        A = torch.tensor(
            [
                [2.0, -2.0, 1.0, 1.0],
                [-3.0, 3.0, -2.0, -1.0],
                [0.0, 0.0, 1.0, 0.0],
                [1.0, 0.0, 0.0, 0.0],
            ],
            device=U.device,
        )
        P = torch.stack([p0, p1, p0dot, p1dot], dim=1)
        ans = U[:, None, :] @ A[None, :, :] @ P
        ans = ans.squeeze(1)
        return ans

    def plot_traj(self, agent, env_index=0):
        for i, u in enumerate(
            torch.linspace(0, 1, len(self.world.traj_points[self.team_name][agent]))
        ):
            pointi = self.world.traj_points[self.team_name][agent][i]
            num_envs = self.objectives[agent]["start_pos"][env_index, :].shape[0]
            posi = self.hermite(
                self.objectives[agent]["start_pos"][env_index, :],
                self.objectives[agent]["target_pos"][env_index, :],
                self.objectives[agent]["start_vel"][env_index, :],
                self.objectives[agent]["target_vel"][env_index, :],
                u=torch.tensor([u] * num_envs, device=self.world.device),
                deriv=0,
            )
            if env_index == Ellipsis or (
                isinstance(env_index, torch.Tensor)
                and env_index.dtype == torch.bool
                and torch.all(env_index)
            ):
                pointi.set_pos(
                    torch.as_tensor(posi, device=self.world.device),
                    batch_index=None,
                )
            elif isinstance(env_index, int):
                pointi.set_pos(
                    torch.as_tensor(posi, device=self.world.device),
                    batch_index=env_index,
                )
            elif isinstance(env_index, list):
                for envi in env_index:
                    pointi.set_pos(
                        torch.as_tensor(posi, device=self.world.device)[envi, :],
                        batch_index=env_index[envi],
                    )
            elif (
                isinstance(env_index, torch.Tensor)
                and env_index.dtype == torch.bool
                and torch.any(env_index)
            ):
                envs = torch.where(env_index)
                for i, envi in enumerate(envs):
                    pointi.set_pos(
                        torch.as_tensor(posi, device=self.world.device)[i, :],
                        batch_index=envi[0],
                    )

    def clamp_pos(self, pos, return_bool=False):
        orig_pos = pos.clone()
        agent_size = self.world.agent_size
        pitch_y = self.world.pitch_width / 2 - agent_size
        pitch_x = self.world.pitch_length / 2 - agent_size
        goal_y = self.world.goal_size / 2 - agent_size
        goal_x = self.world.goal_depth
        pos[:, Y] = torch.clamp(pos[:, Y], -pitch_y, pitch_y)
        inside_goal_y_mask = torch.abs(pos[:, Y]) < goal_y
        pos[~inside_goal_y_mask, X] = torch.clamp(
            pos[~inside_goal_y_mask, X], -pitch_x, pitch_x
        )
        pos[inside_goal_y_mask, X] = torch.clamp(
            pos[inside_goal_y_mask, X], -pitch_x - goal_x, pitch_x + goal_x
        )
        if return_bool:
            return torch.any(pos != orig_pos, dim=-1)
        else:
            return pos

    def nPr(self, n, r):
        if r > n:
            return 0
        ans = 1
        for k in range(n, max(1, n - r), -1):
            ans = ans * k
        return ans

    def combine_or(self, seq):
        return reduce(
            operator.or_,
            seq,
            torch.zeros(seq[0].shape, device=self.world.device).bool(),
        )

    def combine_mask(self, env_index, mask):
        if env_index == Ellipsis:
            return mask
        elif isinstance(env_index, torch.Tensor) and env_index.dtype == torch.bool:
            if isinstance(mask, torch.Tensor) and mask.dtype == torch.bool:
                new_env_index = env_index.clone()
                new_env_index[env_index] = mask
                return new_env_index
            else:
                return torch.arange(env_index.shape[0], device=self.world.device)[mask]
        elif isinstance(env_index, torch.Tensor) and env_index.dtype == torch.int:
            return env_index[mask]
        elif isinstance(env_index, list):
            return torch.tensor(env_index, device=self.world.device)[mask]

    def check_possession(self, env_index=Ellipsis):
        agents_pos = torch.stack(
            [agent.state.pos[env_index] for agent in self.teammates + self.opposition],
            dim=1,
        )
        agents_vel = torch.stack(
            [agent.state.vel[env_index] for agent in self.teammates + self.opposition],
            dim=1,
        )
        ball_pos = self.ball.state.pos[env_index]
        ball_vel = self.ball.state.vel[env_index]
        disps = ball_pos[:, None, :] - agents_pos
        relvels = ball_vel[:, None, :] - agents_vel
        dists = (disps + relvels * self.possession_lookahead).norm(dim=-1)
        mindist_agent = torch.argmin(dists[:, : len(self.teammates)], dim=-1)
        mindist_team = torch.argmin(dists, dim=-1) < len(self.teammates)
        for i, agent in enumerate(self.teammates):
            self.agent_possession[agent][env_index] = mindist_agent == i
        self.team_possession[env_index] = mindist_team

    def check_better_positions(self, agent, role, env_index=Ellipsis):
        curr_pos = agent.state.pos[env_index]
        curr_target = self.objectives[agent]["target_pos"]
        samples = (
            torch.randn(
                self.nsamples,
                curr_pos.shape[0],
                self.world.dim_p,
                device=self.world.device,
            )
            * self.sigma
            + curr_pos[None, :, :]
        )
        test_pos = torch.cat(
            [curr_target[None, :, :], samples], dim=0
        )  # curr_pos[None,:,:],
        test_pos_shape = test_pos.shape
        test_pos = self.clamp_pos(
            test_pos.view(test_pos_shape[0] * test_pos_shape[1], test_pos_shape[2])
        ).view(*test_pos_shape)
        values = torch.stack(
            [
                self.get_pos_value(
                    test_pos[i], role=role, agent=agent, env_index=env_index
                )
                for i in range(test_pos.shape[0])
            ],
            dim=0,
        )
        values[0, :] += self.replan_margin
        highest_value = values.argmax(dim=0)
        best_pos = torch.gather(
            test_pos,
            dim=0,
            index=highest_value.unsqueeze(0)
            .unsqueeze(-1)
            .expand(-1, -1, self.world.dim_p),
        )
        return best_pos[0, :, :]

    def get_angle_interval(self, pos, obj, objpos=None, beams=128, env_index=Ellipsis):
        # agent_pos = agent.state.pos[env_index]
        if objpos is not None:
            obj_pos = objpos
        else:
            obj_pos = obj.state.pos[env_index]
        if obj == self.target_net or obj == self.own_net:
            left_goal_mask = obj_pos[:, X] < 0
            inner_centre = obj_pos.clone()
            inner_centre[:, X] += (
                self.world.goal_depth / 2 * (left_goal_mask.float() * 2 - 1)
            )
            obj_side1 = inner_centre.clone()
            obj_side1[:, Y] += self.world.goal_size / 2
            obj_side2 = inner_centre.clone()
            obj_side2[:, Y] += -self.world.goal_size / 2
        elif isinstance(obj.shape, Sphere):
            centre_disp = obj_pos - pos
            centre_dist = centre_disp.norm(dim=-1)
            centre_disp[centre_dist == 0] = torch.tensor(
                [0.02, 0], device=self.world.device
            )
            centre_dir = centre_disp / centre_dist[:, None]
            normal_dir = torch.stack([-centre_dir[:, Y], centre_dir[:, X]], dim=-1)
            obj_side1 = obj_pos + normal_dir * obj.shape.radius
            obj_side2 = obj_pos - normal_dir * obj.shape.radius
        disp_side1 = obj_side1 - pos
        disp_side2 = obj_side2 - pos
        dir_side1 = disp_side1 / disp_side1.norm(dim=-1)[:, None]
        dir_side2 = disp_side2 / disp_side2.norm(dim=-1)[:, None]
        angle_1 = torch.atan2(dir_side1[:, X], dir_side1[:, Y])
        angle_2 = torch.atan2(dir_side2[:, X], dir_side2[:, Y])
        angle_less = torch.minimum(angle_1, angle_2)
        angle_greater = torch.maximum(angle_1, angle_2)
        lidar = torch.zeros(angle_less.shape[0], beams, device=self.world.device).bool()
        lidar_angles = torch.linspace(
            -torch.pi,
            torch.pi - (2 * torch.pi / beams),
            beams,
            device=self.world.device,
        )
        wraparound_mask = (angle_greater > torch.pi / 2) & (angle_less < -torch.pi / 2)
        covered_angles = (angle_less[:, None] <= lidar_angles[None, :]) & (
            angle_greater[:, None] >= lidar_angles[None, :]
        )
        covered_angles_wraparound = (angle_less[:, None] >= lidar_angles[None, :]) & (
            angle_greater[:, None] <= lidar_angles[None, :]
        )
        lidar[~wraparound_mask] = covered_angles[~wraparound_mask]
        lidar[wraparound_mask] = covered_angles_wraparound[wraparound_mask]
        return lidar, lidar_angles

    def get_separations(
        self,
        pos,
        agent=None,
        teammate=True,
        wall=True,
        opposition=False,
        env_index=Ellipsis,
    ):
        disps = []
        if wall:
            top_wall_dist = -pos[:, Y] + self.world.pitch_width / 2
            bottom_wall_dist = pos[:, Y] + self.world.pitch_width / 2
            left_wall_dist = pos[:, X] + self.world.pitch_length / 2
            right_wall_dist = -pos[:, X] + self.world.pitch_length / 2
            vertical_wall_disp = torch.zeros(pos.shape, device=self.world.device)
            vertical_wall_disp[:, Y] = torch.minimum(top_wall_dist, bottom_wall_dist)
            vertical_wall_disp[bottom_wall_dist < top_wall_dist, Y] *= -1
            horizontal_wall_disp = torch.zeros(pos.shape, device=self.world.device)
            horizontal_wall_disp[:, X] = torch.minimum(left_wall_dist, right_wall_dist)
            horizontal_wall_disp[left_wall_dist < right_wall_dist, X] *= -1
            disps.append(vertical_wall_disp)
            disps.append(horizontal_wall_disp)
        if teammate:
            for otheragent in self.teammates:
                if otheragent != agent:
                    agent_disp = otheragent.state.pos[env_index] - pos
                    disps.append(agent_disp)
        if opposition:
            for otheragent in self.opposition:
                if otheragent != agent:
                    agent_disp = otheragent.state.pos[env_index] - pos
                    disps.append(agent_disp)
        return disps

    def get_lane_value(self, pos, agent, opposition=False, env_index=Ellipsis):
        if not opposition:
            ball_angles, lidar_angles = self.get_angle_interval(pos, self.ball)
            goal_angles, _ = self.get_angle_interval(
                pos, self.target_net, env_index=env_index
            )
            blocking_angles_list = [
                self.get_angle_interval(pos, otheragent, env_index=env_index)[0]
                for otheragent in self.teammates + self.opposition
                if (otheragent != agent)
            ]
            desired_angles = ball_angles | goal_angles
            blocking_angles = self.combine_or(blocking_angles_list)
            unblocked_angles = desired_angles & ~blocking_angles
            unblocked_angle_ratio = unblocked_angles.sum(dim=-1) / desired_angles.sum(
                dim=-1
            )
            unblocked_angle_ratio[torch.isnan(unblocked_angle_ratio)] = 0.0
            return unblocked_angle_ratio
        else:
            opp_lane_value = 0.0
            for opp_agent in self.opposition:
                opp_agent_pos = opp_agent.state.pos[env_index]
                opp_desired_angles = self.get_angle_interval(
                    opp_agent_pos, self.own_net, env_index=env_index
                )[0]
                opp_blocking_angles_list = [
                    self.get_angle_interval(
                        opp_agent_pos,
                        otheragent,
                        objpos=pos,
                        env_index=env_index,
                    )[0]
                    for otheragent in self.teammates
                ]
                opp_unblocked_angles = opp_desired_angles & ~self.combine_or(
                    opp_blocking_angles_list
                )
                opp_unblocked_angle_ratio = opp_unblocked_angles.sum(
                    dim=-1
                ) / opp_desired_angles.sum(dim=-1)
                opp_lane_value += -opp_unblocked_angle_ratio
            opp_lane_value /= len(self.opposition)
            return opp_lane_value

    def get_pos_value(self, pos, role=0.5, agent=None, env_index=Ellipsis):
        # The value of a position for movement
        # Single agent's sight on goal and the ball, blocked by teammates and opposition
        lane_value = self.get_lane_value(
            pos, agent, opposition=False, env_index=env_index
        )
        # Agent Separations
        dists = self.get_separations(pos, agent, env_index=env_index)
        dists = torch.stack([dist.norm(dim=-1) for dist in dists], dim=-1)
        inv_sq_dists = dists ** (-2)
        separation_value = -inv_sq_dists.sum(dim=-1)
        # Entire opposition's sight on goal, blocked by all teammates (shared value for all teammates)
        opp_lane_value = self.get_lane_value(
            pos, agent, opposition=True, env_index=env_index
        )
        # Value Calculation
        values = (
            self.separation_weight * separation_value
            + self.lane_weight * role * lane_value
            + self.lane_weight * (1 - role) * opp_lane_value
        )
        return values

    def get_attack_value(self, agent, env_index=Ellipsis):
        # The value of a position for attacking purposes
        agent_pos = agent.state.pos[env_index]
        lane_value = self.attack_lane_weight * self.get_lane_value(
            agent.state.pos[env_index],
            agent,
            opposition=False,
            env_index=env_index,
        )

        goal_dist = (agent_pos - self.target_net.state.pos[env_index]).norm(dim=-1)
        goal_dist_value = self.attack_goal_dist_weight * -goal_dist

        opp_dists = self.get_separations(
            agent_pos,
            agent,
            teammate=False,
            wall=False,
            opposition=True,
            env_index=env_index,
        )
        opp_dists = torch.stack(
            [opp_dist.norm(dim=-1) for opp_dist in opp_dists], dim=-1
        )
        opp_dist = torch.min(opp_dists, dim=-1)[0]
        opp_dist_value = self.attack_defender_dist_weight * opp_dist
        return lane_value + goal_dist_value + opp_dist_value

    def can_shoot(self, agent, env_index=Ellipsis):
        # Distance
        ball_pos = self.ball.state.pos[env_index]
        goal_dist = (ball_pos - self.target_net.state.pos[env_index]).norm(dim=-1)
        within_range_mask = goal_dist < self.shooting_dist
        # Angle
        beams = 128
        goal_angles, lidar_angles = self.get_angle_interval(
            ball_pos, self.target_net, beams=beams, env_index=env_index
        )
        blocking_angles_list = [
            self.get_angle_interval(
                ball_pos, otheragent, beams=beams, env_index=env_index
            )[0]
            for otheragent in self.teammates + self.opposition
            if (otheragent != agent)
        ]
        unblocked_angles = goal_angles & ~self.combine_or(blocking_angles_list)
        unblocked_angles[:, 0] = False
        unblocked_angles[:, -1] = False
        indicesxy = torch.where(
            unblocked_angles[:, :-1].int() - unblocked_angles[:, 1:].int()
        )
        indicesx = indicesxy[0].view(-1, 2)[:, 0]
        indicesy = indicesxy[1].view(-1, 2)
        n = (
            torch.zeros(unblocked_angles.shape[0], device=self.world.device)
            .int()
            .scatter_reduce(
                index=indicesx,
                src=(indicesy[:, 1] - indicesy[:, 0]).int(),
                dim=0,
                reduce="sum",
            )
        )
        midpt = (
            torch.zeros(unblocked_angles.shape[0], device=self.world.device)
            .float()
            .scatter_reduce(
                index=indicesx,
                src=(indicesy[:, 1] + indicesy[:, 0])
                / 2
                * (indicesy[:, 1] - indicesy[:, 0]),
                dim=0,
                reduce="sum",
            )
            / n
            + 0.5
        )
        midpt[torch.isnan(midpt)] = 0
        within_angle_mask = n * (2 * torch.pi / beams) >= self.shooting_angle
        # Result
        can_shoot_mask = within_range_mask & within_angle_mask
        frac = midpt - torch.floor(midpt)
        shoot_angle = (1 - frac) * lidar_angles[torch.ceil(midpt).long()] + (
            frac
        ) * lidar_angles[torch.floor(midpt).long()]
        shoot_dir = torch.stack(
            [torch.sin(shoot_angle), torch.cos(shoot_angle)], dim=-1
        )
        shoot_pos = ball_pos + shoot_dir * (
            goal_dist[:, None] + self.shoot_on_goal_dist
        )
        return can_shoot_mask, shoot_pos

    def can_pass(self, agent_dest, env_index=Ellipsis):
        # Distance
        ball_pos = self.ball.state.pos[env_index]
        agent_pos = agent_dest.state.pos[env_index]
        agent_dist = (ball_pos - agent_pos).norm(dim=-1)
        within_range_mask = agent_dist <= self.shooting_dist
        # Angle
        beams = 128
        goal_angles, lidar_angles = self.get_angle_interval(
            ball_pos, agent_dest, beams=beams, env_index=env_index
        )
        blocking_angles_list = [
            self.get_angle_interval(
                ball_pos, otheragent, beams=beams, env_index=env_index
            )[0]
            for otheragent in self.teammates + self.opposition
            if (otheragent != agent_dest)
        ]
        unblocked_angles = goal_angles & ~self.combine_or(blocking_angles_list)
        passing_angle = unblocked_angles.sum(dim=-1) * (2 * torch.pi / beams)
        within_angle_mask = passing_angle >= self.passing_angle
        can_pass_mask = within_range_mask & within_angle_mask
        return can_pass_mask

# Run
if __name__ == "__main__":
    render_interactively(
        __file__,
        control_two_agents=True,
        continuous=True,
        n_blue_agents=3,
        n_red_agents=3,
        ai_red_agents=False,
        ai_blue_agents=False,
        dense_reward_ratio=0.001,
    )
