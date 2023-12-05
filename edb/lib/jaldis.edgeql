#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2018-present MagicStack Inc. and the EdgeDB authors.
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
#

CREATE MODULE ext::jaldis;


## Functions
## ---------

CREATE FUNCTION
ext::jaldis::generate_content_id(content_type: std::int64) -> std::uuid
{
    CREATE ANNOTATION std::description := 'Return a typed content UUID.';
    SET volatility := 'Volatile';
    USING EDGEQL $$
        with unix_ts_ns := ((<int64>datetime_get(datetime_of_statement(), 'epochseconds') * 1000000000) + <int64>str_split(str_split(<str>datetime_of_statement(), '.')[1], '+')[0] * 1000),
             sixteen_secs := 16000000000,

             t1 := math::floor(unix_ts_ns / sixteen_secs),
             rest1 := unix_ts_ns % sixteen_secs,
             t2 := math::floor(bit_lshift(rest1, 16) / sixteen_secs),
             rest2 := bit_lshift(rest1, 16) % sixteen_secs,
             t3 := bit_lshift(rest2, 12) / sixteen_secs,

            uuid_bytes := to_bytes(<int32>t1) ++ to_bytes(<int32>t2)[2:4] ++ to_bytes(<int16>t3 + <int16>bit_lshift(<int16>8, 12)) ++ to_bytes(<int16>bit_lshift(<int16>2, 14)) ++ to_bytes(<int16>bit_lshift(<int16>content_type, 2)) ++ to_bytes(uuid_generate_v4())[11:15]

        select <uuid>bytes_encode(uuid_bytes, 'hex')
    $$;
};


CREATE FUNCTION
ext::jaldis::generate_typed_id(content_type: std::int64) -> std::uuid
{
    CREATE ANNOTATION std::description := 'Return a typed content UUID.';
    SET volatility := 'Volatile';
    USING EDGEQL $$
        with
          microseconds := math::floor(((<int64>datetime_get(datetime_of_statement(), 'epochseconds') * 1000) + <int64>str_split(str_split(<str>datetime_of_statement(), '.')[1], '+')[0] / 1000)),
          content_type := to_bytes(<int16>bit_lshift(content_type, 2)),
          rand := to_bytes(uuid_generate_v4()),

          uuid_bytes := to_bytes(<int64>microseconds)[2:] ++ rand[6:10] ++ content_type ++ rand[12:16],
          uuid_hex := bytes_encode(uuid_bytes, 'hex')

        select <uuid>(uuid_hex[0:12] ++ "8" ++ uuid_hex[13:32])
    $$;
};


CREATE FUNCTION
ext::jaldis::uuid_generate_v7() -> std::uuid
{
    CREATE ANNOTATION std::description := 'Return a UUIDv7.';
    SET volatility := 'Volatile';
    USING SQL $$
        SELECT encode(
            set_bit(
                set_bit(
                    overlay(uuid_send(gen_random_uuid())
                        placing substring(int8send(floor(extract(epoch from clock_timestamp()) * 1000)::bigint) from 3)
                        from 1 for 6
                    ),
                52, 1
            ),
            53, 1
        ),
        'hex')::uuid
    $$;
};
