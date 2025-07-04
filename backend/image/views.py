from django.utils import timezone

from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from django.shortcuts import get_list_or_404
from rest_framework.generics import get_object_or_404
from rest_framework.views import APIView

from .models import Images, Historys, Favoriteimages
from .serializers import ImageSimpleSerializer,ImageDetailSerializer,ImageCreateSerializer
from .util import image_to_braille, makeTag_from_file, list_ads_image_urls, insert_ads_randomly

import random

#이미지들에 대한 기능 - 전체조회 최신순
class ImagesAPIView(APIView):
    #image list retrive
    def get(self, request):
        #정렬 파라미터 받기 (기본값: -createDate)
        sort_param = request.query_params.get('sort', '-createDate')

        sort_field = sort_param.lstrip('-')
        # 허용된 필드 목록
        ALLOWED_SORT_FIELDS = ['createDate', 'title', 'viewCount']
        #유효성 검사
        if sort_field not in ALLOWED_SORT_FIELDS:
            sort_param = '-createDate'  # 기본값으로 대체

        images = Images.objects.all().order_by(sort_param)
        paginator = PageNumberPagination()
        paginator.page_size = 10 #한 페이지에 10개씩

        result_page = paginator.paginate_queryset(images, request)
        serializer = ImageSimpleSerializer(result_page,many=True,context={'request': request})

        # 광고 이미지 URL 리스트 불러오기
        # 한 페이지에 랜덤하게 하나 삽입
        ads_urls = list_ads_image_urls()
        if ads_urls:
            # 광고 이미지를 랜덤으로 하나 선택
            random_ad_url = random.choice(ads_urls)
            # 광고 이미지를 더미데이터로 만들어줌
            ad_dict = {
                "imageID": None,
                "title": "광고",
                "imageURL": random_ad_url,
                "is_favorite": False
            }
            # 리스트에 광고 랜덤 삽입
            data_with_ad = insert_ads_randomly(serializer.data, ad_dict)
        else:
            data_with_ad = serializer.data

        return paginator.get_paginated_response(data_with_ad)

#전체조회 - 조회수 기준
class ImagesViewCountAPIView(APIView):
    #image list retrive
    def get(self, request):
        images = Images.objects.all().order_by('-viewCount')
        paginator = PageNumberPagination()
        paginator.page_size = 10  # 한 페이지에 10개씩

        result_page = paginator.paginate_queryset(images, request)
        serializer = ImageSimpleSerializer(result_page,many=True,context={'request': request})
        return paginator.get_paginated_response(serializer.data)

#이미지 하나에 대한 기능 - 상세조회
class ImageAPIView(APIView):
    #detail image
    def get(self, request, imageID):
        image = get_object_or_404(Images, imageID=imageID)

        #viewCount increase
        image.viewCount += 1
        image.save(update_fields=["viewCount"])

        # 로그인된 유저이면 시청기록 추가
        if request.user.is_authenticated:
            print('확인')
            history, created = Historys.objects.get_or_create(userID=request.user, imageID=image)
            # 기존 기록의 createDate를 현재 시간으로 갱신
            if not created:
                history.watchDate = timezone.now()
                history.save()

        serializer = ImageDetailSerializer(image,context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

#제목으로 조회한 이미지들
class ImagesByTitleAPIView(APIView):
    #retrieve by title
    def get(self, request, title):
        # 정렬 파라미터 받기 (기본값: -createDate)
        sort_param = request.query_params.get('sort', '-createDate')
        sort_field = sort_param.lstrip('-')
        # 허용된 필드 목록
        ALLOWED_SORT_FIELDS = ['createDate', 'title', 'viewCount']
        # 유효성 검사
        if sort_field not in ALLOWED_SORT_FIELDS:
            sort_param = '-createDate'  # 기본값으로 대체

        images = Images.objects.filter(title__istartswith=title).order_by('-createDate')
        paginator = PageNumberPagination()
        paginator.page_size = 10  # 한 페이지에 10개씩

        result_page = paginator.paginate_queryset(images, request)
        serializer = ImageSimpleSerializer(result_page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

#내가 올린 이미지 조회
class MyImagesAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        images = Images.objects.filter(userID=request.user).order_by('-createDate')
        serializer = ImageSimpleSerializer(images, many=True,context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

#로그인 인증이 필요한 기능 - 업로드 / 수정 / 삭제
class ImageAuthAPIView(APIView):
    permission_classes = [IsAuthenticated]
    # image create
    def post(self, request):
        serializer = ImageCreateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(userID=request.user)
            # s3 에서 객체 경로 받아와서
            # RDS 저장 full 전체 경로로 저장하기
            # 불러오기도 DB
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    # modify image
    def put(self, request, imageID):
        image = get_object_or_404(Images, imageID=imageID)
        serializer = ImageCreateSerializer(image, data=request.data)
        if image.userID != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if serializer.is_valid():
            serializer.save(userID=request.user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    # delete image
    def delete(self, request, imageID):
        image = get_object_or_404(Images, imageID=imageID)
        if image.userID != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        #s3 삭제
        if image.imageURL:
            image.imageURL.delete(save=False)
        #DB 삭제
        image.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

#즐겨찾기 기능 - 조회/추가/삭제
class FavoriteAPIView(APIView):
    permission_classes = [IsAuthenticated]
    #즐겨찾기 조회
    def get(self,request):
        favorites = Favoriteimages.objects.filter(userID=request.user).order_by('-createDate').select_related('imageID')
        images = [f.imageID for f in favorites]
        serializer = ImageSimpleSerializer(images, many=True,context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    #즐겨찾기에 추가
    def post(self, request):
        image = get_object_or_404(Images, imageID=request.data.get('imageID'))
        Favoriteimages.objects.create(userID=request.user, imageID=image)
        return Response({"usrID":request.user.id, "imageID":image.imageID},status=status.HTTP_201_CREATED)
    #즐겨찾기 삭제
    def delete(self,request, imageID):
        favorite = get_object_or_404(Favoriteimages, imageID=imageID, userID=request.user)
        if favorite.userID == request.user:
            favorite.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(status=status.HTTP_403_FORBIDDEN)

#시청기록 기능 - 조회/삭제
class HistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]
    #시청기록 조회
    def get(self,request):
        history = Historys.objects.filter(userID=request.user).order_by('-watchDate').select_related('imageID')
        images = [h.imageID for h in history]
        serializer = ImageSimpleSerializer(images, many=True,context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    #시청기록 삭제
    def delete(self,request, imageID):
        history = get_object_or_404(Historys, imageID=imageID, userID=request.user)
        if history.userID == request.user:
            history.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(status=status.HTTP_403_FORBIDDEN)

#태그 자동 생성 기능
class TagAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        image_file = request.FILES.get('imageURL')
        if not image_file:
            return Response({'error': 'No image file provided'}, status=status.HTTP_400_BAD_REQUEST)

        predicted_tags = makeTag_from_file(image_file)
        return Response({'tags': predicted_tags}, status=status.HTTP_200_OK)

#도트아트로 변환
class TextChangeAPIView(APIView):
    def get(self,request, imageID):
        image = get_object_or_404(Images, imageID=imageID)
        text = image_to_braille(image.imageURL.url)
        return Response({'text':text},status=status.HTTP_200_OK)

