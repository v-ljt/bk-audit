# -*- coding: utf-8 -*-
"""
TencentBlueKing is pleased to support the open source community by making
蓝鲸智云 - 审计中心 (BlueKing - Audit Center) available.
Copyright (C) 2023 THL A29 Limited,
a Tencent company. All rights reserved.
Licensed under the MIT License (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
either express or implied. See the License for the
specific language governing permissions and limitations under the License.
We undertake not to change the open source license (MIT license) applicable
to the current version of the project delivered to anyone in the future.
"""

import abc
from collections import defaultdict

from bk_resource import resource
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.utils.translation import gettext, gettext_lazy
from pypinyin import lazy_pinyin

from apps.audit.resources import AuditMixinResource
from apps.meta.constants import NO_TAG_ID, NO_TAG_NAME
from apps.meta.models import Tag
from apps.permission.handlers.actions.action import ActionEnum
from apps.permission.handlers.drf import wrapper_permission_field
from core.models import get_request_username
from core.utils.page import paginate_queryset
from services.web.strategy_v2.models import StrategyTool
from services.web.tool.constants import ToolTypeEnum
from services.web.tool.models import Tool, ToolTag
from services.web.tool.serializers import (
    ListRequestSerializer,
    ListToolTagsResponseSerializer,
    ToolCreateRequestSerializer,
    ToolDeleteRetrieveRequestSerializer,
    ToolListAllResponseSerializer,
    ToolListResponseSerializer,
    ToolResponseSerializer,
    ToolRetrieveResponseSerializer,
    ToolUpdateRequestSerializer,
)
from services.web.tool.tool import (
    create_tool_with_config,
    custom_sort_order,
    recent_tool_usage_manager,
    sync_resource_tags,
)


class ToolBase(AuditMixinResource, abc.ABC):
    tags = ["Tool"]


class ListToolTags(ToolBase):
    name = gettext_lazy("列出工具标签")
    ResponseSerializer = ListToolTagsResponseSerializer
    many_response_data = True

    def perform_request(self, validated_request_data):
        tag_count = list(ToolTag.objects.values("tag_id").annotate(tool_count=Count("tag_id")).order_by())
        tag_map = {t.tag_id: {"name": t.tag_name} for t in Tag.objects.all()}
        for t in tag_count:
            t.update({"tag_name": tag_map.get(t["tag_id"], {}).get("name", t["tag_id"])})

        tag_count.sort(key=lambda tag: [lazy_pinyin(tag["tag_name"].lower(), errors="ignore"), tag["tag_name"].lower()])

        tag_count = [
            {
                "tag_name": str(NO_TAG_NAME),
                "tag_id": NO_TAG_ID,
                "tool_count": Tool.all_latest_tools()
                .exclude(uid__in=ToolTag.objects.values_list("tool_uid", flat=True).distinct())
                .count(),
            }
        ] + tag_count

        return tag_count


class ListTool(ToolBase):
    name = gettext_lazy("获取工具列表")
    RequestSerializer = ListRequestSerializer
    bind_request = True

    def perform_request(self, validated_request_data):
        request = validated_request_data.pop("_request")
        tags = validated_request_data.pop("tags", [])
        keyword = validated_request_data.get("keyword", "").strip()
        my_created = validated_request_data["my_created"]
        recent_used = validated_request_data["recent_used"]

        current_user = get_request_username()

        queryset = Tool.all_latest_tools()

        if recent_used:
            recent_tool_uids = recent_tool_usage_manager.get_recent_uids(current_user)
            if not recent_tool_uids:
                return []
            else:
                queryset = queryset.filter(uid__in=recent_tool_uids)

        if my_created:
            queryset = queryset.filter(created_by=current_user)

        if keyword:
            keyword_filter = (
                Q(name__icontains=keyword) | Q(description__icontains=keyword) | Q(created_by__icontains=keyword)
            )
            queryset = queryset.filter(keyword_filter)

        if int(NO_TAG_ID) in tags:
            tagged_tool_uids = ToolTag.objects.values_list("tool_uid", flat=True).distinct()
            queryset = queryset.exclude(uid__in=tagged_tool_uids)
        elif tags:
            tagged_tool_uids = ToolTag.objects.filter(tag_id__in=tags).values_list("tool_uid", flat=True).distinct()
            queryset = queryset.filter(uid__in=tagged_tool_uids)

        if recent_used and recent_tool_uids:
            queryset = custom_sort_order(queryset, "uid", recent_tool_uids)
        else:
            queryset = queryset.order_by("-updated_at")
        paged_tools, page = paginate_queryset(queryset=queryset, request=request)
        tool_uids = [t.uid for t in paged_tools]

        # 查询 tags
        tool_tags = ToolTag.objects.filter(tool_uid__in=tool_uids)
        tag_map = defaultdict(list)
        for t in tool_tags:
            tag_map[t.tool_uid].append(str(t.tag_id))

        # 查询关联策略
        strategy_map = defaultdict(list)
        rows = StrategyTool.objects.filter(tool_uid__in=tool_uids).values("tool_uid", "strategy_id")
        for row in rows:
            strategy_map[row["tool_uid"]].append(row["strategy_id"])

        for tool in paged_tools:
            setattr(tool, "tags", tag_map.get(tool.uid, []))
            setattr(tool, "strategies", strategy_map.get(tool.uid, []))

        serialized_data = ToolListResponseSerializer(instance=paged_tools, many=True).data

        data = wrapper_permission_field(
            result_list=serialized_data,
            actions=[ActionEnum.USE_TOOL],
            id_field=lambda item: item["uid"],
            always_allowed=lambda item: item.get("created_by") == current_user,
        )
        return page.get_paginated_response(data=data)


class DeleteTool(ToolBase):
    name = gettext_lazy("删除工具")
    RequestSerializer = ToolDeleteRetrieveRequestSerializer

    @transaction.atomic
    def perform_request(self, validated_request_data):
        uid = validated_request_data["uid"]
        Tool.delete_by_uid(uid)


class CreateTool(ToolBase):
    name = gettext_lazy("新增工具")
    RequestSerializer = ToolCreateRequestSerializer  # 统一使
    ResponseSerializer = ToolResponseSerializer

    def perform_request(self, validated_request_data):
        return create_tool_with_config(validated_request_data)


class UpdateTool(ToolBase):
    name = gettext_lazy("编辑工具")
    RequestSerializer = ToolUpdateRequestSerializer
    ResponseSerializer = ToolResponseSerializer

    @transaction.atomic
    def perform_request(self, validated_request_data):
        uid = validated_request_data["uid"]
        tag_names = validated_request_data.pop("tags")
        tool = Tool.last_version_tool(uid)
        if not tool:
            raise Http404(gettext("Tool not found: %s") % uid)
        if "config" in validated_request_data:
            new_config = validated_request_data["config"]
            if tool.config != new_config:
                new_tool_data = {
                    "uid": tool.uid,
                    "tool_type": tool.tool_type,
                    "name": validated_request_data.get("name", tool.name),
                    "description": validated_request_data.get("description", tool.description),
                    "namespace": validated_request_data.get("namespace", tool.namespace),
                    "version": tool.version + 1,
                    "config": new_config,
                }
                if tool.tool_type == ToolTypeEnum.DATA_SEARCH:
                    new_tool_data["data_search_config_type"] = tool.data_search_config.data_search_config_type
                return create_tool_with_config(new_tool_data)
        for key, value in validated_request_data.items():
            setattr(tool, key, value)
        tool.save(update_fields=validated_request_data.keys())
        sync_resource_tags(
            resource_uid=tool.uid,
            tag_names=tag_names,
            relation_model=ToolTag,
            relation_resource_field="tool_uid",
        )
        return tool


class ExecuteTool(ToolBase):
    name = gettext_lazy("工具执行")

    def perform_request(self, validated_request_data):
        pass


class ListToolAll(ToolBase):
    name = gettext_lazy("工具列表(all)")
    many_response_data = True
    ResponseSerializer = ToolListAllResponseSerializer

    def perform_request(self, validated_request_data):
        tool_qs = Tool.all_latest_tools().order_by("-updated_at")
        tool_uids = [tool.uid for tool in tool_qs]
        tool_tags = ToolTag.objects.filter(tool_uid__in=tool_uids)

        tag_map = defaultdict(list)
        for t in tool_tags:
            tag_map[t.tool_uid].append(str(t.tag_id))
        strategy_map = defaultdict(list)
        rows = StrategyTool.objects.filter(tool_uid__in=tool_uids).values("tool_uid", "strategy_id")
        for row in rows:
            strategy_map[row["tool_uid"]].append(row["strategy_id"])

        for tool in tool_qs:
            setattr(tool, "tags", tag_map.get(tool.uid, []))
            setattr(tool, "strategies", strategy_map.get(tool.uid, []))
        serialized_data = ToolListAllResponseSerializer(tool_qs, many=True).data

        current_user = get_request_username()
        data = wrapper_permission_field(
            result_list=serialized_data,
            actions=[ActionEnum.USE_TOOL],
            id_field=lambda item: item["uid"],
            always_allowed=lambda item: item.get("created_by") == current_user,
        )
        return data


class ExportToolData(ToolBase):
    name = gettext_lazy("工具执行数据导出")

    def perform_request(self, validated_request_data):
        pass


class GetToolDetail(ToolBase):
    name = gettext_lazy("获取工具详情")
    RequestSerializer = ToolDeleteRetrieveRequestSerializer
    ResponseSerializer = ToolRetrieveResponseSerializer

    def perform_request(self, validated_request_data):
        uid = validated_request_data["uid"]
        tool = Tool.last_version_tool(uid=uid)
        if not tool:
            raise Http404(gettext("Tool not found: %s") % uid)

        tag_ids = list(ToolTag.objects.filter(tool_uid=tool.uid).values_list("tag_id", flat=True))
        setattr(tool, "tags", [str(tid) for tid in tag_ids])

        # 如果是SQL工具且有引用表，检查表权限
        if tool.tool_type == ToolTypeEnum.DATA_SEARCH and tool.config.get("referenced_tables"):
            tables = [table["table_name"] for table in tool.config["referenced_tables"]]
            auth_results = {
                item["object_id"]: item for item in resource.tool.user_query_table_auth_check({"tables": tables})
            }
            # 将权限信息添加到每个表
            for table in tool.config["referenced_tables"]:
                table["permission"] = auth_results.get(table["table_name"], {})
        return tool
