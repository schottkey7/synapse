# -*- coding: utf-8 -*-
# Copyright 2015 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ._base import Config


class MetricsConfig(Config):
    def __init__(self, args):
        super(MetricsConfig, self).__init__(args)
        self.enable_metrics = args.enable_metrics
        self.metrics_port = args.metrics_port

    @classmethod
    def add_arguments(cls, parser):
        super(MetricsConfig, cls).add_arguments(parser)
        metrics_group = parser.add_argument_group("metrics")
        metrics_group.add_argument(
            '--enable-metrics', dest="enable_metrics", action="store_true",
            help="Enable collection and rendering of performance metrics"
        )
        metrics_group.add_argument(
            '--metrics-port', metavar="PORT", type=int,
            help="Separate port to accept metrics requests on (on localhost)"
        )
