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

from tests import unittest

from synapse.metrics.metric import CounterMetric


class CounterMetricTestCase(unittest.TestCase):

    def test_scalar(self):
        counter = CounterMetric("scalar")

        self.assertEquals(counter.render(), [
            "scalar 0",
        ])

        counter.inc()

        self.assertEquals(counter.render(), [
            "scalar 1",
        ])

        counter.inc()
        counter.inc()

        self.assertEquals(counter.render(), [
            "scalar 3"
        ])

    def test_vector(self):
        counter = CounterMetric("vector", keys=["method"])

        # Empty counter doesn't yet know what values it has
        self.assertEquals(counter.render(), [])

        counter.inc("GET")

        self.assertEquals(counter.render(), [
            "vector{method=GET} 1",
        ])

        counter.inc("GET")
        counter.inc("PUT")

        self.assertEquals(counter.render(), [
            "vector{method=GET} 2",
            "vector{method=PUT} 1",
        ])